"""Download the example box; project operations read local files."""

import fcntl
import io
import os
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from importlib.resources import files
from pathlib import Path

import certifi

from kitflow.catalog import CURRENT_SCHEMA, Catalog, KitFlowError, safe_path
from kitflow.settings import box_path

MAX_FILE_BYTES = 2 * 1024 * 1024


DEFAULT_REPOSITORY = "Joynik/KitFlow"


def read_instructions(local: Path | None = None) -> str:
    """Prefer user instructions; fall back to the bundled usage guide offline."""
    root = local if local is not None else box_path()
    for instruction in (root / "INSTRUCTION.md", root / "default/INSTRUCTION.md"):
        if instruction.is_file():
            return instruction.read_text(encoding="utf-8")
    compiled = globals().get("__compiled__")
    if compiled is not None:
        # A package data directory named kitflow would collide with the executable.
        return (Path(compiled.python_runtime_dir) / "INSTRUCTION.md").read_text(encoding="utf-8")
    source_guide = Path(__file__).resolve().parents[2] / "docs/INSTRUCTION.md"
    if source_guide.is_file():
        return source_guide.read_text(encoding="utf-8")
    return files("kitflow").joinpath("INSTRUCTION.md").read_text(encoding="utf-8")


def fetch(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise KitFlowError("Catalog requests must use https://api.github.com")
    headers = {"User-Agent": "KitFlow/0.1", "Accept": "application/vnd.github+json"}
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or certifi.where())
    limit = 32 * 1024 * 1024 if "/tarball/" in parsed.path else MAX_FILE_BYTES
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise KitFlowError("GitHub download exceeds size limit")
    return data


def github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    executable = shutil.which("gh")
    if executable:
        try:
            result = subprocess.run(
                [executable, "auth", "token", "--hostname", "github.com"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except OSError, subprocess.TimeoutExpired:
            pass
    return None


def extract_box(content: bytes, destination: Path):
    """Read only box entries; never let archive extraction follow links."""
    total = 0
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for index, member in enumerate(archive):
            if index >= 10000:
                raise KitFlowError("Standard box archive contains too many entries")
            parts = member.name.split("/")
            if len(parts) < 3 or parts[1] != "box":
                continue
            relative = "/".join(parts[2:]).rstrip("/")
            if not relative or ".DS_Store" in Path(relative).parts:
                continue
            target = safe_path(destination, relative)
            if relative in seen:
                raise KitFlowError(f"Duplicate standard box entry: {relative}")
            seen.add(relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile() and not member.issym():
                raise KitFlowError(f"Unsupported standard box entry: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                if relative == "kitflow-box.toml" or Path(member.linkname).is_absolute():
                    raise KitFlowError(
                        f"Only relative template symbolic links are supported: {relative}"
                    )
                target.symlink_to(member.linkname)
            else:
                total += member.size
                if member.size > MAX_FILE_BYTES or total > 64 * 1024 * 1024:
                    raise KitFlowError("Standard box contents exceed size limit")
                stream = archive.extractfile(member)
                if stream is None:
                    raise KitFlowError(f"Cannot read standard box entry: {relative}")
                with stream:
                    target.write_bytes(stream.read())


def seed_box(destination: Path):
    """Install the initial box without replacing any existing user directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination.parent, os.O_RDONLY)
    staging = None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KitFlowError("Another KitFlow command is preparing the user box") from error
        if destination.exists() or destination.is_symlink():
            return
        staging = Path(tempfile.mkdtemp(prefix=".box-download-", dir=destination.parent))
        print("Downloading standard box…", file=sys.stderr, flush=True)
        archive = fetch(f"https://api.github.com/repos/{DEFAULT_REPOSITORY}/tarball/main")
        extract_box(archive, staging)
        (staging / "INSTRUCTION.md").write_text(read_instructions(staging), encoding="utf-8")
        Catalog(staging)
        staging.rename(destination)
        staging = None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise KitFlowError(
            f"Cannot prepare the initial box: {error}. Retry online or use --box PATH."
        ) from error
    except (ValueError, TypeError, tarfile.TarError) as error:
        raise KitFlowError(f"Invalid initial box: {error}") from error
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        os.close(descriptor)


def prepare_user_directories(destination: Path):
    for name in ("tasks", "templates"):
        directory = safe_path(destination, name)
        directory.mkdir(exist_ok=True)
    manifest = safe_path(destination, "kitflow-box.toml")
    if not manifest.exists():
        with manifest.open("x", encoding="utf-8") as stream:
            stream.write(
                f"# User overrides for the standard box in default/.\nschema = {CURRENT_SCHEMA}\n"
            )


def initialize_box(destination: Path):
    """Publish the complete initial layout only after the standard download succeeds."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".box-initialize-", dir=destination.parent) as folder:
        staging = Path(folder) / "box"
        staging.mkdir()
        seed_box(staging / "default")
        prepare_user_directories(staging)
        Catalog(staging)
        if destination.exists() or destination.is_symlink():
            raise KitFlowError("The box appeared during initialization; retry")
        staging.rename(destination)


def load_box(local: Path | None = None) -> tuple[Catalog, dict]:
    if local is not None:
        return Catalog(local.resolve()), {"local": str(local.resolve())}
    destination = box_path()
    if not destination.exists() and not destination.is_symlink():
        initialize_box(destination)
    return Catalog(destination), {"kind": "user-box"}
