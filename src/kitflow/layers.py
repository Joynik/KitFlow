"""Combine standard definitions with explicit user overrides."""

import re
import tomllib
from pathlib import Path

from kitflow.catalog import KitFlowError, safe_path

SECTIONS = ("components", "files", "tasks", "env", "defaults")


def read_data(root: Path) -> dict:
    path = safe_path(root, "kitflow-box.toml")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if type(data.get("schema")) is not int or data["schema"] not in {1, 2}:
        raise KitFlowError(f"{path}: unsupported catalog schema; expected 1 or 2")
    return data


def rows_by_id(data: dict, section: str) -> dict[str, dict]:
    rows = data.get(section, [])
    if not isinstance(rows, list):
        raise KitFlowError(f"{section} must be an array of tables")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise KitFlowError(f"{section} entries must be tables")
        # Legacy task fragments remain addressable by their template stem.
        identity = row.get("id")
        if identity is None and section == "tasks":
            identity = Path(row.get("template", "")).stem
        if identity is None and section == "env":
            identity = row.get("name")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", identity):
            raise KitFlowError(f"Invalid {section} ID: {identity}")
        if identity in result:
            raise KitFlowError(f"Duplicate {section} ID: {identity}")
        result[identity] = row
    return result


def disabled_ids(data: dict) -> dict[str, list[str]]:
    disabled = data.get("disabled", {})
    if not isinstance(disabled, dict) or set(disabled) - {*SECTIONS, "profiles"}:
        raise KitFlowError("disabled accepts components, files, tasks, env, defaults and profiles")
    for section, values in disabled.items():
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise KitFlowError(f"disabled.{section} must be an array of IDs")
        if len(values) != len(set(values)):
            raise KitFlowError(f"disabled.{section} contains duplicate IDs")
    return disabled


def load_data(root: Path, standard: Path | None) -> tuple[dict, list[tuple[Path, dict]]]:
    sources = []
    if standard is not None:
        sources.append((standard, read_data(standard)))
    sources.append((root, read_data(root)))
    combined = {"schema": max(data["schema"] for _, data in sources)}
    disabled = {}
    for _, data in sources:
        for section, values in disabled_ids(data).items():
            disabled.setdefault(section, set()).update(values)
    for section in SECTIONS:
        rows = {}
        for _, data in sources:
            rows.update(rows_by_id(data, section))
        for identity in disabled.get(section, set()):
            if identity not in rows:
                raise KitFlowError(f"Unknown disabled {section} ID: {identity}")
            del rows[identity]
        combined[section] = list(rows.values())
    combined["disabled"] = {key: sorted(values) for key, values in disabled.items()}
    return combined, sources
