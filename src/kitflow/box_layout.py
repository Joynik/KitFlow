"""Resolve and validate the two local Box layers."""

import fcntl
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def present(path: Path) -> bool:
    return path.is_symlink() or path.exists()


def layer_paths(root: Path) -> tuple[Path, Path | None]:
    personal = root / "personal"
    standard = root / "standard"
    if present(personal) or present(standard):
        return personal, standard if present(standard) else None
    return root, None


@contextmanager
def locked_box(root: Path) -> Generator[None]:
    from kitflow.catalog import KitFlowError

    descriptor = os.open(root, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KitFlowError("Another KitFlow command is changing the Box") from error
        yield
    finally:
        os.close(descriptor)


def resolve_layer(path: Path) -> Path:
    from kitflow.catalog import KitFlowError

    if path.is_symlink() and not path.is_dir():
        raise KitFlowError(f"Unavailable symbolic link to Box directory: {path}")
    return path.resolve()


def validate_box_links(root: Path):
    personal, standard = layer_paths(root)
    validate_links(personal)
    if standard is not None and personal != root:
        validate_links(standard)


def validate_links(root: Path):
    """Check links before using a Box, including links inside linked directories."""
    from kitflow.catalog import KitFlowError

    visited = set()

    def visit(path: Path, link: Path | None = None):
        if path.is_symlink():
            link = path
        try:
            info = path.stat()
            if stat.S_ISDIR(info.st_mode):
                identity = (info.st_dev, info.st_ino)
                if identity in visited:
                    return
                visited.add(identity)
                for child in sorted(path.iterdir()):
                    visit(child, link)
            elif link == path:
                if not stat.S_ISREG(info.st_mode):
                    raise KitFlowError(f"Symbolic link target is not a file or directory: {path}")
                with path.open("rb"):
                    pass
        except OSError as error:
            if link is not None:
                raise KitFlowError(f"Unavailable symbolic link: {link} ({error})") from error
            raise

    if present(root):
        visit(root)
