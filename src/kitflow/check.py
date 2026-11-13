"""Read-only validation of box definitions and connected project configuration."""

import json
import re
import tomllib
from pathlib import Path

from kitflow import mise
from kitflow.catalog import Artifact, Catalog, KitFlowError, safe_path
from kitflow.engine import CONFIG, load_config, plan, read_file

BOX_FIELDS = {
    "components": {"id", "label", "category", "description", "requires", "conflicts"},
    "files": {"id", "path", "template", "when", "mode", "empty"},
    "tasks": {"name", "template", "when"},
    "env": {"name", "value", "when"},
}


def known_fields(value, allowed: set[str], location: str):
    if not isinstance(value, dict):
        raise KitFlowError(f"{location} must be a table")
    unknown = set(value) - allowed
    if unknown:
        raise KitFlowError(f"Unknown fields in {location}: {', '.join(sorted(unknown))}")


def validate_box(root: Path) -> Catalog:
    data = tomllib.loads((root / "kitflow-box.toml").read_text(encoding="utf-8"))
    known_fields(data, {"schema", *BOX_FIELDS}, "box")
    if type(data.get("schema")) is not int:
        raise KitFlowError("schema must be an integer")
    for section, allowed in BOX_FIELDS.items():
        rows = data.get(section, [])
        if not isinstance(rows, list):
            raise KitFlowError(f"{section} must be an array of tables")
        for index, row in enumerate(rows, 1):
            location = f"{section}[{index}]"
            known_fields(row, allowed, location)
            if "description" in row and not isinstance(row["description"], str):
                raise KitFlowError(f"{location}.description must be a string")
            if "empty" in row and type(row["empty"]) is not bool:
                raise KitFlowError(f"{location}.empty must be a boolean")
    return Catalog(root)


def validate_project(root: Path) -> dict:
    content = read_file(root / CONFIG)
    if content is None:
        raise KitFlowError("Project configuration is missing")
    data = tomllib.loads(content.decode("utf-8"))
    known_fields(data, {"schema", "selection", "source", "state"}, "project")
    if type(data.get("schema")) is not int:
        raise KitFlowError("schema must be an integer")
    known_fields(data.get("selection", {}), {"components", "excluded"}, "selection")
    state = data.get("state", {})
    known_fields(state, {"artifacts"}, "state")
    records = state.get("artifacts", {})
    if not isinstance(records, dict):
        raise KitFlowError("state.artifacts must be a table")
    for identity, record in records.items():
        location = f"state.artifacts.{identity}"
        known_fields(record, {"path", "kind", "key", "sha256", "once"}, location)
        if isinstance(record.get("path"), str):
            safe_path(root, record["path"])
        if "once" in record and type(record["once"]) is not bool:
            raise KitFlowError(f"{location}.once must be a boolean")
        checksum = record.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise KitFlowError(
                f"{location}.sha256 must contain 64 lowercase hexadecimal characters"
            )
    document = load_config(root)
    for field in ("components", "excluded"):
        values = document["selection"].get(field, [])
        if len(values) != len(set(values)):
            raise KitFlowError(f"selection.{field} contains duplicate IDs")
    return document


def validate_syntax(path: Path, suffix: str | None = None):
    suffix = suffix or path.suffix.lower()
    if suffix not in {".toml", ".json"} or not path.exists():
        return
    content = read_file(path)
    if content is not None:
        text = content.decode("utf-8")
        if suffix == ".toml":
            tomllib.loads(text)
        else:
            json.loads(text)


def configuration_issues(box: Path, project: Path) -> list[tuple[Path, str]]:
    issues = []
    catalog = None
    errors = (KitFlowError, OSError, ValueError, TypeError)
    try:
        catalog = validate_box(box)
    except errors as error:
        issues.append((box / "kitflow-box.toml", str(error)))
    if catalog is not None:
        checked = set()
        for row in catalog.data.get("files", []):
            if row.get("empty") is True:
                continue
            target = safe_path(catalog.root, row["template"])
            suffix = Path(row["path"]).suffix.lower()
            if target.suffix.lower() in {".toml", ".json"}:
                suffix = target.suffix.lower()
            if (target, suffix) in checked:
                continue
            checked.add((target, suffix))
            try:
                validate_syntax(target, suffix)
            except errors as error:
                issues.append((target, str(error)))
    if not project.is_dir():
        issues.append((project, "Project directory does not exist"))
        return issues
    if not (project / CONFIG).exists() and not (project / CONFIG).is_symlink():
        return issues
    document = None
    try:
        document = validate_project(project)
        if catalog is not None:
            plan(project, catalog, document["selection"].get("components", []), document)
    except errors as error:
        issues.append((project / CONFIG, str(error)))
    if document is not None and catalog is not None:
        try:
            artifacts = catalog.render(document["selection"].get("components", []))
        except errors:
            artifacts = {}
        excluded = document["selection"].get("excluded", [])
        formats = {
            row["id"]: Path(row.get("template", "")).suffix.lower()
            for row in catalog.data.get("files", [])
        }
        for identity, artifact in artifacts.items():
            if artifact.kind != "file" or identity in excluded:
                continue
            try:
                suffix = formats.get(identity)
                if suffix not in {".toml", ".json"}:
                    suffix = None
                validate_syntax(safe_path(project, artifact.path), suffix)
            except errors as error:
                issues.append((project / artifact.path, str(error)))
    path = project / "mise.toml"
    try:
        content = read_file(path)
        if content is not None:
            text = content.decode("utf-8")
            mise.parse(text)
            for identity, span in mise.blocks(text).items():
                prefix, _, key = identity.partition(".")
                if prefix not in {"task", "env"} or not key:
                    raise KitFlowError(f"Unknown managed block ID: {identity}")
                mise.validate_span(
                    text, Artifact(identity, "mise.toml", b"", kind=prefix, key=key), span
                )
    except errors as error:
        issues.append((path, str(error)))
    return issues
