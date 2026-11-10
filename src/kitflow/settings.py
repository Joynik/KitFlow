"""Locations of user-owned KitFlow configuration."""

import os
from pathlib import Path


def config_directory() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kitflow"


def box_path() -> Path:
    return config_directory()
