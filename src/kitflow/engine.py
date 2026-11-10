"""Read-only planning and guarded, rollback-capable application."""

import fcntl
import hashlib
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit

from kitflow import mise
from kitflow.catalog import Artifact, Catalog, KitFlowError, safe_path

CONFIG = "kitflow.toml"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_file(path: Path) -> bytes | None:
    if path.is_symlink():
        raise KitFlowError(f"Symbolic links are not managed: {path.name}")
    if path.exists():
        if not path.is_file():
            raise KitFlowError(f"Expected a file: {path}")
        return path.read_bytes()
    return None


def load_config(root: Path) -> dict:
    content = read_file(root / CONFIG)
    if content is None:
        return {"schema": 1, "selection": {"components": [], "excluded": []}, "state": {}}
    try:
        document = tomlkit.parse(content.decode())
        if document.get("schema") != 1:
            raise KitFlowError("Unsupported kitflow.toml schema")
        selection = document["selection"]
        for name in ("components", "excluded"):
            value = selection.get(name, [])
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                raise KitFlowError(f"selection.{name} must be an array")
        for section in ("source", "state"):
            if not isinstance(document.get(section, {}), dict):
                raise KitFlowError(f"{section} must be a table")
        records = document.get("state", {}).get("artifacts", {})
        if not isinstance(records, dict):
            raise KitFlowError("state.artifacts must be a table")
        for identity, record in records.items():
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise KitFlowError(f"Invalid state record: {identity}")
            kind = record.get("kind", "file")
            if kind not in {"file", "task", "env"}:
                raise KitFlowError(f"Invalid artifact kind: {identity}")
            if kind != "file" and record["path"] != "mise.toml":
                raise KitFlowError("Task and environment state must target mise.toml")
            if kind == "file" and record["path"] == "mise.toml":
                raise KitFlowError("mise.toml cannot be managed as a whole file")
            for field_name in ("key", "sha256"):
                if not isinstance(record.get(field_name), str):
                    raise KitFlowError(f"Invalid {field_name} in state record: {identity}")
        for value in document.get("source", {}).values():
            if not isinstance(value, str):
                raise KitFlowError("Source settings must be strings")
        return document
    except (ValueError, KeyError, TypeError) as error:
        raise KitFlowError(f"Invalid kitflow.toml: {error}") from error


@dataclass
class Change:
    artifact: Artifact
    before: bytes | None
    after: bytes | None
    operation: str
    conflict: bool = False
    reason: str = ""
    decision: str = "apply"


@dataclass
class Plan:
    root: Path
    document: dict
    selected: list[str]
    changes: list[Change] = field(default_factory=list)
    snapshots: dict[str, bytes | None] = field(default_factory=dict)


def plan(root: Path, catalog: Catalog, selected: list[str], document: dict) -> Plan:
    root = root.resolve()
    selected = catalog.resolve(selected)
    result = Plan(root, deepcopy(document), selected)
    result.snapshots[CONFIG] = read_file(root / CONFIG)
    records = document.get("state", {}).get("artifacts", {})
    excluded = set(document.get("selection", {}).get("excluded", []))
    desired = catalog.render(selected)
    candidates = dict(desired)
    for identity, record in records.items():
        if identity not in candidates:
            candidates[identity] = Artifact(
                identity,
                record["path"],
                b"",
                record.get("once", False),
                record.get("kind", "file"),
                record.get("key", ""),
            )
        elif record["path"] != candidates[identity].path:
            raise KitFlowError(f"Template path changed for {identity}; detach or remove it first")
    for identity, artifact in candidates.items():
        if identity in excluded:
            continue
        path = safe_path(root, artifact.path)
        current_file = read_file(path)
        result.snapshots[artifact.path] = current_file
        current = current_file
        record = records.get(identity)
        target = desired.get(identity)
        if artifact.kind != "file":
            text = (current_file or b"").decode()
            mise.parse(text)
            span = mise.blocks(text).get(identity)
            if span:
                mise.validate_span(text, artifact, span)
                current = span[2].encode()
            else:
                current = None
                if record or mise.collision(text, artifact):
                    result.changes.append(
                        Change(
                            artifact,
                            None,
                            None,
                            "detach",
                            reason="User-owned mise entry or removed markers",
                        )
                    )
                    continue
        if artifact.once:
            if current is None and target and not record:
                result.changes.append(Change(artifact, None, target.content, "create"))
            continue
        if target and current == target.content:
            if not record or record.get("sha256") != digest(current):
                result.changes.append(Change(artifact, current, target.content, "adopt"))
            continue
        if not target and current is None:
            result.changes.append(Change(artifact, None, None, "forget"))
            continue
        conflict = current is not None and (not record or digest(current) != record.get("sha256"))
        operation = "delete" if not target else "create" if current is None else "update"
        result.changes.append(
            Change(
                artifact,
                current,
                target.content if target else None,
                operation,
                conflict,
                "Locally modified or existing user file" if conflict else "",
                "pending" if conflict else "apply",
            )
        )
    return result


def atomic_write(path: Path, content: bytes, mode: int | None = None):
    descriptor, temporary = tempfile.mkstemp(prefix=".kitflow-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode if mode is not None else 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply(result: Plan, source: dict):
    descriptor = os.open(result.root, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise KitFlowError("Another KitFlow command is updating this project") from error
        _apply(result, source)
    finally:
        os.close(descriptor)


def _apply(result: Plan, source: dict):
    if any(change.decision == "pending" for change in result.changes):
        raise KitFlowError("Resolve conflicts before applying; --yes does not overwrite conflicts")
    document = deepcopy(result.document)
    document["schema"] = 1
    selection = document.setdefault("selection", {})
    selection["components"] = result.selected
    excluded = set(selection.get("excluded", []))
    state = document.setdefault("state", {})
    records = state.setdefault("artifacts", {})
    document["source"] = source
    writes: dict[str, bytes | None] = {}
    mise_text = (result.snapshots.get("mise.toml") or b"").decode()
    for change in result.changes:
        artifact = change.artifact
        if change.decision == "skip":
            continue
        if change.decision == "keep" or change.operation == "detach":
            excluded.add(artifact.id)
            records.pop(artifact.id, None)
            continue
        if change.operation == "forget":
            records.pop(artifact.id, None)
            continue
        if artifact.kind == "file":
            if change.operation != "adopt":
                writes[artifact.path] = change.after
        else:
            mise_text = mise.replace(mise_text, artifact, change.after)
            writes["mise.toml"] = mise_text.encode()
        if change.after is None:
            records.pop(artifact.id, None)
        else:
            records[artifact.id] = {
                "path": artifact.path,
                "kind": artifact.kind,
                "key": artifact.key,
                "sha256": digest(change.after),
                "once": artifact.once,
            }
    selection["excluded"] = sorted(excluded)
    if "mise.toml" in writes:
        mise.parse(mise_text)
    writes[CONFIG] = tomlkit.dumps(document).encode()
    for name, before in result.snapshots.items():
        path = result.root / CONFIG if name == CONFIG else safe_path(result.root, name)
        if read_file(path) != before:
            raise KitFlowError(f"{name} changed after planning; run the command again")
    changed = []
    directories = []
    modes = {}
    try:
        for name, content in writes.items():
            path = result.root / CONFIG if name == CONFIG else safe_path(result.root, name)
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                directories.append(parent)
            modes[name] = path.stat().st_mode & 0o777 if path.exists() else None
            changed.append(name)
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, content, modes[name])
    except BaseException:
        for name in reversed(changed):
            path = result.root / name
            before = result.snapshots.get(name)
            if before is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, before, modes[name])
        for directory in reversed(directories):
            directory.rmdir()
        raise
