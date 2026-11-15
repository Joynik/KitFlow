"""Replace the standard box snapshot while preserving user overrides."""

import fcntl
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from kitflow.catalog import KitFlowError, safe_path
from kitflow.check import configuration_issues
from kitflow.source import prepare_user_directories, seed_box


def snapshot(root: Path) -> dict[str, bytes | str]:
    if not root.exists():
        return {}
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = os.readlink(path)
        elif path.is_file():
            result[name] = path.read_bytes()
        elif not path.is_dir():
            raise KitFlowError(f"Not a regular box entry: {path}")
    return result


def refresh_box(
    destination: Path,
    review: Callable[[dict[str, bytes | str], dict[str, bytes | str]], bool],
) -> int:
    if destination.is_symlink() or not destination.is_dir():
        raise KitFlowError("Initialize a real box directory with kitflow before updating it")
    standard = safe_path(destination, "default")
    descriptor = os.open(destination, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KitFlowError("Another KitFlow command is updating the standard box") from error
        with tempfile.TemporaryDirectory(prefix=".box-refresh-", dir=destination.parent) as folder:
            staging = Path(folder)
            incoming = staging / "incoming"
            seed_box(incoming)
            # Validate user overrides against the new standard before changing anything.
            validate_update(destination, incoming)
            before = snapshot(standard)
            after = snapshot(incoming)
            count = sum(
                before.get(name) != after.get(name) for name in before.keys() | after.keys()
            )
            user_before = snapshot_user(destination)
            if not count or not review(before, after):
                return 0
            if snapshot(standard) != before:
                raise KitFlowError("Standard box changed during review; retry")
            validate_update(destination, incoming)
            prepare_user_directories(destination)
            if snapshot_user(destination) != user_before:
                # Directory scaffolding is allowed; existing user files must stay untouched.
                raise KitFlowError("User box changed during update; retry")
            backup = staging / "previous"
            had_standard = standard.exists()
            if had_standard:
                standard.rename(backup)
            try:
                incoming.rename(standard)
            except BaseException:
                if had_standard:
                    backup.rename(standard)
                raise
            return count
    finally:
        os.close(descriptor)


def snapshot_user(root: Path) -> dict[str, bytes | str]:
    return {
        name: value for name, value in snapshot(root).items() if not name.startswith("default/")
    }


def validate_update(destination: Path, incoming: Path):
    issues = configuration_issues(destination, destination, standard=incoming)
    if issues:
        raise KitFlowError(
            "Invalid standard box update:\n"
            + "\n".join(f"{path}: {message}" for path, message in issues)
        )
