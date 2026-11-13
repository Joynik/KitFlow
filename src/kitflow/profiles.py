"""Local setup profiles are snapshots of component selections, not project bindings."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from kitflow.catalog import Catalog, KitFlowError, safe_path


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    components: list[str]


def profile_paths(catalog: Catalog) -> list[Path]:
    directory = safe_path(catalog.root, "profiles")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise KitFlowError("profiles must be a directory")
    return sorted(directory.glob("*.toml"))


def read_profile(catalog: Catalog, path: Path) -> Profile:
    try:
        safe_path(catalog.root, path.relative_to(catalog.root).as_posix())
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", path.stem):
            raise KitFlowError("Profile filename must be a lowercase component-style ID")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        unknown = set(data) - {"name", "description", "components"}
        if unknown:
            raise KitFlowError(f"Unknown profile fields: {', '.join(sorted(unknown))}")
        name = data.get("name")
        description = data.get("description", "")
        if not isinstance(name, str) or not name.strip():
            raise KitFlowError("Profile name must be a nonempty string")
        if not isinstance(description, str):
            raise KitFlowError("Profile description must be a string")
        components = data.get("components")
        if not isinstance(components, list) or any(not isinstance(x, str) for x in components):
            raise KitFlowError("Profile components must be an array of component IDs")
        if len(components) != len(set(components)):
            raise KitFlowError("Profile components contains duplicate IDs")
        return Profile(path.stem, name, description, catalog.resolve(components))
    except (KitFlowError, OSError, ValueError) as error:
        raise KitFlowError(f"{path}: {error}") from error


def load_profiles(catalog: Catalog) -> dict[str, Profile]:
    return {path.stem: read_profile(catalog, path) for path in profile_paths(catalog)}
