"""Download the example box; project operations read local files."""

import base64
import fcntl
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
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
    accept = (
        "application/vnd.github.raw+json"
        if "/contents/" in parsed.path
        else "application/vnd.github+json"
    )
    headers = {"User-Agent": "KitFlow/0.1", "Accept": accept}
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or certifi.where())
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        data = response.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise KitFlowError("Catalog file exceeds 2 MiB limit")
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


def content_url(repository: str, commit: str, path: str) -> str:
    return (
        f"https://api.github.com/repos/{repository}/contents/"
        f"{urllib.parse.quote(path, safe='/')}?ref={commit}"
    )


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
        commit = json.loads(
            fetch(f"https://api.github.com/repos/{DEFAULT_REPOSITORY}/commits/main")
        )["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise KitFlowError("GitHub returned an invalid commit")
        manifest = fetch(content_url(DEFAULT_REPOSITORY, commit, "box/kitflow-box.toml"))
        (staging / "kitflow-box.toml").write_bytes(manifest)
        tree = json.loads(
            fetch(
                f"https://api.github.com/repos/{DEFAULT_REPOSITORY}/git/trees/{commit}?recursive=1"
            )
        )
        if tree.get("truncated"):
            raise KitFlowError("GitHub returned an incomplete box file list")
        for entry in tree["tree"]:
            name = entry["path"]
            if not name.startswith("box/") or entry.get("type") == "tree":
                continue
            relative = name.removeprefix("box/")
            if ".DS_Store" in Path(relative).parts:
                continue
            mode = entry.get("mode")
            if entry.get("type") != "blob" or mode not in {"100644", "100755", "120000"}:
                raise KitFlowError(f"Unsupported standard box entry: {name}")
            target = safe_path(staging, relative)
            if relative == "kitflow-box.toml":
                if mode == "120000":
                    raise KitFlowError("The box manifest must be a regular file")
                continue
            content = (
                fetch(content_url(DEFAULT_REPOSITORY, commit, name)) if mode != "120000" else b""
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                sha = entry.get("sha", "")
                if not re.fullmatch(r"[a-f0-9]{40}", sha):
                    raise KitFlowError(f"Invalid symbolic link blob: {name}")
                blob = json.loads(
                    fetch(f"https://api.github.com/repos/{DEFAULT_REPOSITORY}/git/blobs/{sha}")
                )
                if blob.get("encoding") != "base64":
                    raise KitFlowError(f"Invalid symbolic link encoding: {name}")
                link = base64.b64decode(blob["content"]).decode("utf-8")
                if Path(link).is_absolute():
                    raise KitFlowError(f"Only relative symbolic links are supported: {name}")
                target.symlink_to(link)
            else:
                target.write_bytes(content)
        (staging / "INSTRUCTION.md").write_text(read_instructions(staging), encoding="utf-8")
        Catalog(staging)
        staging.rename(destination)
        staging = None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise KitFlowError(
            f"Cannot prepare the initial box: {error}. Retry online or use --box PATH."
        ) from error
    except (KeyError, ValueError, TypeError) as error:
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
