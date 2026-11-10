"""Seed a user-owned box once; all later operations read local files."""

import fcntl
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

from kitflow.catalog import Catalog, KitFlowError, safe_path
from kitflow.settings import box_path

MAX_FILE_BYTES = 2 * 1024 * 1024


DEFAULT_REPOSITORY = "Joynik/KitFlow"


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
        commit = json.loads(
            fetch(f"https://api.github.com/repos/{DEFAULT_REPOSITORY}/commits/main")
        )["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise KitFlowError("GitHub returned an invalid commit")
        manifest = fetch(content_url(DEFAULT_REPOSITORY, commit, "box/kitflow-box.toml"))
        (staging / "kitflow-box.toml").write_bytes(manifest)
        import tomllib

        data = tomllib.loads(manifest.decode())
        downloaded = {"kitflow-box.toml"}
        for section in ("files", "tasks"):
            for row in data.get(section, []):
                if section == "files" and row.get("empty") is True:
                    continue
                name = row["template"]
                target = safe_path(staging, name)
                if name in downloaded:
                    continue
                content = fetch(content_url(DEFAULT_REPOSITORY, commit, "box/" + name))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                downloaded.add(name)
        Catalog(staging)
        staging.rename(destination)
        staging = None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise KitFlowError(
            f"Cannot prepare the initial box: {error}. Retry online or use --catalog PATH."
        ) from error
    except (KeyError, ValueError, TypeError) as error:
        raise KitFlowError(f"Invalid initial box: {error}") from error
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        os.close(descriptor)


def load_box(local: Path | None = None) -> tuple[Catalog, dict]:
    if local is not None:
        return Catalog(local.resolve()), {"local": str(local.resolve())}
    destination = box_path()
    if not destination.exists() and not destination.is_symlink():
        seed_box(destination)
    return Catalog(destination), {"kind": "user-box"}
