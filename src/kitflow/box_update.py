"""Download and review example box changes without removing personal files."""

import fcntl
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from kitflow.catalog import Catalog, KitFlowError, safe_path
from kitflow.engine import atomic_write, read_file
from kitflow.source import seed_box


def refresh_box(destination: Path, decide: Callable[[str, bytes | None, bytes], bool]) -> int:
    if destination.is_symlink():
        raise KitFlowError("Refresh the real box directory instead of a symbolic link")
    descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KitFlowError("Another KitFlow command is preparing the user box") from error
        with tempfile.TemporaryDirectory(prefix=".box-refresh-", dir=destination.parent) as folder:
            staging = Path(folder)
            incoming = staging / "incoming"
            seed_box(incoming)
            merged = staging / "merged"
            shutil.copytree(destination, merged, symlinks=True)
            writes = {}
            snapshots = {}
            for candidate in sorted(incoming.rglob("*")):
                if not candidate.is_file():
                    continue
                name = candidate.relative_to(incoming).as_posix()
                target = safe_path(destination, name)
                before = read_file(target)
                after = candidate.read_bytes()
                snapshots[name] = before
                if before == after or not decide(name, before, after):
                    continue
                writes[name] = after
                preview = safe_path(merged, name)
                preview.parent.mkdir(parents=True, exist_ok=True)
                preview.write_bytes(after)
            if not writes:
                return 0
            Catalog(merged)
            for name, before in snapshots.items():
                if read_file(safe_path(destination, name)) != before:
                    raise KitFlowError(f"{name} changed during review; run kitflow again")
            applied = []
            directories = []
            modes = {}
            try:
                for name, content in writes.items():
                    target = safe_path(destination, name)
                    missing = []
                    parent = target.parent
                    while not parent.exists():
                        missing.append(parent)
                        parent = parent.parent
                    for parent in reversed(missing):
                        parent.mkdir()
                        directories.append(parent)
                    modes[name] = target.stat().st_mode & 0o777 if target.exists() else None
                    applied.append(name)
                    atomic_write(target, content, modes[name])
            except BaseException:
                for name in reversed(applied):
                    target = safe_path(destination, name)
                    before = snapshots[name]
                    if before is None:
                        target.unlink(missing_ok=True)
                    else:
                        atomic_write(target, before, modes[name])
                for parent in reversed(directories):
                    parent.rmdir()
                raise
            return len(writes)
    finally:
        os.close(descriptor)
