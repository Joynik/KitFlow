"""Replace the standard box snapshot while preserving user overrides."""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from kitflow.box_layout import layer_paths, locked_box, validate_links
from kitflow.catalog import KitFlowError
from kitflow.check import configuration_issues
from kitflow.source import seed_box


def snapshot(root: Path) -> dict[str, bytes | str]:
    if not root.exists():
        return {}
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if ".DS_Store" in Path(name).parts:
            continue
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
    with locked_box(destination):
        personal, standard = layer_paths(destination)
        if personal == destination or standard is None:
            raise KitFlowError(f"Expected standard/ and personal/ in {destination}")
        validate_links(personal)
        validate_links(standard)
        if standard.is_symlink():
            raise KitFlowError(f"Cannot upgrade a linked standard box: {standard}")
        if personal.resolve().is_relative_to(
            standard.resolve()
        ) or standard.resolve().is_relative_to(personal.resolve()):
            raise KitFlowError(f"Standard and personal Box directories overlap: {personal}")
        with tempfile.TemporaryDirectory(prefix=".box-refresh-", dir=destination.parent) as folder:
            staging = Path(folder)
            incoming = staging / "incoming"
            seed_box(incoming)
            validate_links(incoming)
            validate_update(destination, incoming)
            before = snapshot(standard)
            after = snapshot(incoming)
            count = sum(
                before.get(name) != after.get(name) for name in before.keys() | after.keys()
            )
            user_before = snapshot_user(destination)
            if not count or not review(before, after):
                return 0
            if standard.is_symlink() or snapshot(standard) != before:
                raise KitFlowError("Standard box changed during review; retry")
            validate_links(personal)
            validate_links(standard)
            validate_update(destination, incoming)
            if snapshot_user(destination) != user_before:
                raise KitFlowError("User box changed during update; retry")
            backup = staging / "previous"
            standard.rename(backup)
            try:
                incoming.rename(standard)
                try:
                    validate_links(personal)
                    validate_links(standard)
                except BaseException:
                    standard.rename(incoming)
                    raise
            except BaseException:
                backup.rename(standard)
                raise
            return count


def snapshot_user(root: Path) -> dict[str, bytes | str]:
    personal = root / "personal"
    result = snapshot(personal)
    if personal.is_symlink():
        result["."] = os.readlink(personal)
    return result


def validate_update(destination: Path, incoming: Path):
    issues = configuration_issues(destination, destination, standard=incoming)
    if issues:
        raise KitFlowError(
            "Invalid standard box update:\n"
            + "\n".join(f"{path}: {message}" for path, message in issues)
        )
