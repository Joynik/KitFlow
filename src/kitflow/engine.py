"""Read-only planning and guarded, rollback-capable application."""

import fcntl
import hashlib
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Literal

import tomlkit

from kitflow import file_blocks, manifests, mise
from kitflow.catalog import Artifact, Catalog, KitFlowError, known_fields, safe_path

CONFIG = "kitflow.toml"


def digest(content: bytes | str) -> str:
    value = b"symlink\0" + os.fsencode(content) if isinstance(content, str) else content
    return hashlib.sha256(value).hexdigest()


def read_file(path: Path) -> bytes | None:
    if path.is_symlink():
        raise KitFlowError(f"Symbolic links are not managed: {path.name}")
    if path.exists():
        if not path.is_file():
            raise KitFlowError(f"Expected a file: {path}")
        return path.read_bytes()
    return None


def read_entry(path: Path) -> bytes | str | None:
    """Read a file or the literal link target, never the target contents."""
    return os.readlink(path) if path.is_symlink() else read_file(path)


def load_config(root: Path) -> dict:
    return parse_config(root, read_file(root / CONFIG))


def parse_config(root: Path, content: bytes | None) -> dict:
    if content is None:
        return {"schema": 1, "selection": {"components": [], "excluded": []}, "state": {}}
    try:
        document = tomlkit.parse(content.decode())
        known_fields(
            document,
            {"schema", "box_version", "migrated_box_version", "selection", "source", "state"},
            "project",
        )
        schema = document.get("schema")
        if not isinstance(schema, int) or isinstance(schema, bool) or schema != 1:
            raise KitFlowError("Unsupported kitflow.toml schema")
        for name in ("box_version", "migrated_box_version"):
            version = document.get(name, 0)
            if not isinstance(version, int) or isinstance(version, bool) or version < 0:
                raise KitFlowError(f"{name} must be a nonnegative integer")
        selection = document["selection"]
        known_fields(selection, {"components", "excluded"}, "selection")
        for name in ("components", "excluded"):
            value = selection.get(name, [])
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                raise KitFlowError(f"selection.{name} must be an array")
            if len(value) != len(set(value)):
                raise KitFlowError(f"selection.{name} contains duplicate IDs")
        for section in ("source", "state"):
            if not isinstance(document.get(section, {}), dict):
                raise KitFlowError(f"{section} must be a table")
        state = document.get("state", {})
        known_fields(state, {"artifacts", "seeded_mise_keys", "excluded_paths"}, "state")
        excluded_paths = state.get("excluded_paths", [])
        if not isinstance(excluded_paths, list) or any(
            not isinstance(path, str) for path in excluded_paths
        ):
            raise KitFlowError("Invalid state.excluded_paths")
        for path in excluded_paths:
            safe_path(root, path, allow_link=True)
        records = state.get("artifacts", {})
        seeded = state.get("seeded_mise_keys", [])
        if not isinstance(seeded, list) or any(
            not isinstance(key, list)
            or len(key) < 2
            or key[0] not in ("vars", "env", "settings")
            or any(not isinstance(part, str) for part in key)
            for key in seeded
        ):
            raise KitFlowError("Invalid state.seeded_mise_keys")
        if not isinstance(records, dict):
            raise KitFlowError("state.artifacts must be a table")
        for identity, record in records.items():
            known_fields(
                record, {"path", "kind", "key", "sha256", "once"}, f"state.artifacts.{identity}"
            )
            if not isinstance(record.get("path"), str):
                raise KitFlowError(f"Invalid state record: {identity}")
            kind = record.get("kind", "file")
            if kind not in {"file", "symlink", "block", "task", "env", "defaults"}:
                raise KitFlowError(f"Invalid artifact kind: {identity}")
            if kind in {"task", "env", "defaults"} and record["path"] != "mise.toml":
                raise KitFlowError("Task and environment state must target mise.toml")
            if kind in {"file", "symlink", "block"} and record["path"] == "mise.toml":
                raise KitFlowError("mise.toml cannot be managed as a whole file")
            if not isinstance(record.get("key"), str):
                raise KitFlowError(f"Invalid key in state record: {identity}")
            checksum = record.get("sha256")
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise KitFlowError(f"Invalid sha256 in state record: {identity}")
            if "once" in record and not isinstance(record["once"], bool):
                raise KitFlowError(f"Invalid once in state record: {identity}")
            safe_path(root, record["path"], allow_link=kind in {"file", "symlink", "block"})
        for value in document.get("source", {}).values():
            if not isinstance(value, str):
                raise KitFlowError("Source settings must be strings")
        return document
    except (ValueError, KeyError, TypeError) as error:
        raise KitFlowError(f"Invalid kitflow.toml: {error}") from error


@dataclass
class Change:
    artifact: Artifact
    before: bytes | str | None
    after: bytes | str | None
    operation: str
    conflict: bool = False
    reason: str = ""
    decision: str = "apply"
    state_baseline: bytes | str | None = None
    setting_keys: tuple[tuple[str, ...], ...] = ()


@dataclass
class Plan:
    root: Path
    document: dict
    selected: list[str]
    changes: list[Change] = field(default_factory=list)
    snapshots: dict[str, bytes | str | None] = field(default_factory=dict)
    box_version: int | None = None
    retiring_mise: set[str] = field(default_factory=set)


def resolve_file_directories(
    root: Path, artifacts: dict[str, Artifact], mise_snapshot: bytes | None
) -> dict[str, Artifact]:
    desired = dict(artifacts)
    variables = mise.parse((mise_snapshot or b"").decode()).get("vars", {})
    targets = set()
    for identity, artifact in desired.items():
        if artifact.directory_var and artifact.directory_var in variables:
            directory = variables[artifact.directory_var]
            if not isinstance(directory, str) or "{" in directory:
                raise KitFlowError(f"{artifact.directory_var} must be a literal project directory")
            path = root / directory / Path(artifact.path).name
            if not path.is_relative_to(root):
                raise KitFlowError(f"{artifact.directory_var} must point inside the project")
            artifact = desired[identity] = replace(artifact, path=path.relative_to(root).as_posix())
        if artifact.kind in {"file", "block", "symlink"}:
            if artifact.path in targets:
                raise KitFlowError(f"Duplicate file target: {artifact.path}")
            targets.add(artifact.path)
    return desired


def has_alternative(result: Plan, path: Path, alternatives: tuple[str, ...]) -> bool:
    for alternative in alternatives:
        name, _, key = alternative.partition("#")
        sibling = path.with_name(name)
        if not key or sibling.is_symlink():
            if os.path.lexists(sibling):
                return True
            continue
        relative = sibling.relative_to(result.root).as_posix()
        if relative not in result.snapshots:
            result.snapshots[relative] = read_file(sibling)
        content = result.snapshots[relative]
        if isinstance(content, bytes) and manifests.has_json_key(content, key):
            return True
    return False


def is_excluded(artifact: Artifact, excluded: set[str], paths: set[str]) -> bool:
    name = artifact.exclusion_key
    if artifact.kind not in {"file", "symlink", "block"}:
        return name in excluded
    if ({artifact.id, artifact.path} - {name}).intersection(excluded):
        return True
    if name not in excluded:
        return False
    return artifact.path in paths or not any(PurePosixPath(path).name == name for path in paths)


def plan(
    root: Path,
    catalog: Catalog,
    selected: list[str],
    document: dict,
    *,
    reset: bool = False,
    config_snapshot: bytes | None | Literal[False] = False,
) -> Plan:
    root = root.resolve()
    selected = catalog.resolve(selected)
    result = Plan(root, deepcopy(document), selected)
    result.snapshots[CONFIG] = (
        read_file(root / CONFIG) if config_snapshot is False else config_snapshot
    )
    if result.snapshots[CONFIG] is None and not reset and catalog.version:
        result.box_version = catalog.version
        if catalog.required_migration:
            result.document["migrated_box_version"] = catalog.required_migration
    records = result.document.get("state", {}).get("artifacts", {})
    excluded = set(document.get("selection", {}).get("excluded", []))
    desired = catalog.render(selected)
    if any(artifact.directory_var for artifact in desired.values()):
        snapshot = read_file(root / "mise.toml")
        result.snapshots["mise.toml"] = snapshot
        desired = resolve_file_directories(root, desired, snapshot)
    result.retiring_mise = {
        identity
        for identity, record in records.items()
        if record.get("kind") in {"task", "env"} and identity not in desired
    }
    creation_only = {
        row["id"]
        for row in getattr(catalog, "data", {}).get("files", [])
        if row.get("mode") == "once"
    }
    creation_only.update(identity for identity, artifact in desired.items() if artifact.once)
    block_ids = {
        row["id"]
        for row in getattr(catalog, "data", {}).get("files", [])
        if row.get("mode") == "block"
    }
    for identity, record in records.items():
        if identity.split("/", 1)[0] in creation_only:
            record["once"] = True
    candidates = dict(desired)
    for identity, record in records.items():
        if reset and identity not in desired:
            continue
        if identity not in candidates:
            candidates[identity] = Artifact(
                identity,
                record["path"],
                b"",
                record.get("once", False),
                "block" if identity in block_ids else record.get("kind", "file"),
                record.get("key", ""),
            )
        elif record["path"] != candidates[identity].path and not candidates[identity].directory_var:
            raise KitFlowError(f"Template path changed for {identity}; detach or remove it first")
    state = result.document.setdefault("state", {})
    excluded_paths = {
        path for path in state.get("excluded_paths", []) if PurePosixPath(path).name in excluded
    }
    scoped_names = {PurePosixPath(path).name for path in excluded_paths}
    for artifact in candidates.values():
        if artifact.kind not in {"file", "symlink", "block"}:
            continue
        name = artifact.exclusion_key
        legacy = {artifact.id, artifact.path} - {name}
        if legacy.intersection(excluded) or (name in excluded and name not in scoped_names):
            excluded_paths.add(artifact.path)
    for artifact in candidates.values():
        if artifact.path in excluded_paths and artifact.kind in {"file", "symlink", "block"}:
            excluded.difference_update({artifact.id, artifact.path} - {artifact.exclusion_key})
            excluded.add(artifact.exclusion_key)
    if excluded_paths or "excluded_paths" in state:
        state["excluded_paths"] = sorted(excluded_paths)
    result.document.setdefault("selection", {})["excluded"] = sorted(excluded)
    for identity, artifact in candidates.items():
        if is_excluded(artifact, excluded, excluded_paths) and (
            not reset or artifact.kind in {"task", "env"}
        ):
            continue
        path = safe_path(root, artifact.path, allow_link=artifact.kind in {"file", "symlink"})
        if artifact.path not in result.snapshots:
            result.snapshots[artifact.path] = read_entry(path)
        current_file = result.snapshots[artifact.path]
        current = current_file
        record = records.get(identity)
        target = desired.get(identity)
        if artifact.kind == "block":
            assert not isinstance(current_file, str)
            owned = file_blocks.span(current_file) if current_file is not None else None
            if owned is None and (current_file is not None or record):
                result.changes.append(
                    Change(
                        artifact,
                        None,
                        None,
                        "detach",
                        reason="Missing or damaged KitFlow markers; file left unchanged",
                    )
                )
                continue
            current = owned[2] if owned else None
        if artifact.kind == "defaults":
            if reset and target:
                result.changes.append(Change(artifact, None, target.content, "reset-defaults"))
            elif target and not record:
                assert not isinstance(current_file, str)
                assert isinstance(target.content, bytes)
                content = mise.missing_defaults((current_file or b"").decode(), target.content)
                result.changes.append(
                    Change(
                        artifact,
                        None,
                        content,
                        "create" if content else "adopt",
                        reason="Seed missing user settings",
                    )
                )
            elif not target and record:
                result.changes.append(Change(artifact, None, None, "forget"))
            continue
        if artifact.kind in {"task", "env"}:
            assert not isinstance(current_file, str)
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
        if target and current is None and has_alternative(result, path, target.alternatives):
            continue
        if target and target.additions is not None:
            if isinstance(current, str):
                continue
            assert isinstance(target.content, bytes)
            content = target.content if current is None else current
            if target.additions:
                content = manifests.render_manifest(target.path, content, target.additions)
            if current != content:
                result.changes.append(
                    Change(artifact, current, content, "create" if current is None else "update")
                )
            continue
        if artifact.once and not reset:
            if current is None and target and (not record or artifact.directory_var):
                result.changes.append(Change(artifact, None, target.content, "create"))
            continue
        if target and current == target.content:
            if (
                not record
                or record.get("sha256") != digest(current)
                or record.get("kind", "file") != target.kind
            ):
                result.changes.append(Change(artifact, current, target.content, "adopt"))
            continue
        if not target and current is None:
            result.changes.append(Change(artifact, None, None, "forget"))
            continue
        conflict = (
            not reset
            and artifact.kind != "block"
            and current is not None
            and (
                not record
                or digest(current) != record.get("sha256")
                or isinstance(current, str) != (record.get("kind", "file") == "symlink")
            )
        )
        operation = "delete" if not target else "create" if current is None else "update"
        if artifact.kind == "block" and not target:
            operation = "remove-block"
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
    removed_components = set(document.get("selection", {}).get("components", [])) - set(selected)
    if not reset and (removed_components or result.retiring_mise):
        active_keys = set()
        for artifact in desired.values():
            if artifact.kind == "defaults":
                assert isinstance(artifact.content, bytes)
                active_keys.update(mise.setting_keys(mise.parse(artifact.content.decode())))
            elif artifact.kind == "env":
                active_keys.add(("env", artifact.key))
        seeded_keys = map(tuple, document.get("state", {}).get("seeded_mise_keys", []))
        obsolete = tuple(
            sorted(
                key
                for key in seeded_keys
                if not any(
                    key[: len(active)] == active or active[: len(key)] == key
                    for active in active_keys
                )
            )
        )
        if obsolete:
            if "mise.toml" not in result.snapshots:
                result.snapshots["mise.toml"] = read_file(root / "mise.toml")
            artifact = Artifact("defaults.cleanup", "mise.toml", b"", True, "defaults")
            result.changes.append(
                Change(
                    artifact,
                    None,
                    None,
                    "cleanup-settings",
                    reason="Remove if departing mise entries are removed: "
                    + ", ".join(".".join(key) for key in obsolete),
                    setting_keys=obsolete,
                )
            )
    return result


def preview_files(result: Plan) -> dict[str, tuple[bytes | str | None, bytes | str | None]]:
    """Render the exact selected-file candidates without writing anything."""
    after = {}
    for change in result.changes:
        if change.operation in {"detach", "forget", "adopt"}:
            continue
        artifact = change.artifact
        before = after.get(artifact.path, result.snapshots.get(artifact.path))
        if artifact.kind in {"task", "env", "defaults"}:
            assert not isinstance(before, str)
            after[artifact.path] = update_mise((before or b"").decode(), change).encode()
        elif artifact.kind == "block":
            assert not isinstance(before, str)
            assert not isinstance(change.after, str)
            after[artifact.path] = file_blocks.replace(before, change.after)
        else:
            after[artifact.path] = change.after
    return {
        name: (result.snapshots.get(name), content)
        for name, content in after.items()
        if result.snapshots.get(name) != content
    }


def update_mise(text: str, change: Change) -> str:
    assert isinstance(change.after, bytes) or change.after is None
    if change.artifact.kind == "defaults":
        if change.operation == "cleanup-settings":
            return mise.remove_defaults(text, change.setting_keys)
        assert change.after is not None
        if change.operation == "reset-defaults":
            return mise.reset_defaults(text, change.after)
        return mise.add_defaults(text, change.after)
    return mise.replace(text, change.artifact, change.after)


def atomic_write(path: Path, content: bytes | str, mode: int | None = None):
    descriptor, temporary = tempfile.mkstemp(prefix=".kitflow-", dir=path.parent)
    try:
        if isinstance(content, str):
            os.close(descriptor)
            Path(temporary).unlink()
            os.symlink(content, temporary)
        else:
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
    excluded_paths = set(state.get("excluded_paths", []))
    seeded_keys = set(map(tuple, state.get("seeded_mise_keys", [])))
    records = state.setdefault("artifacts", {})
    document["source"] = source
    writes: dict[str, bytes | str | None] = {}
    mise_snapshot = result.snapshots.get("mise.toml")
    assert not isinstance(mise_snapshot, str)
    mise_text = (mise_snapshot or b"").decode()
    retained_mise = {
        change.decision
        for change in result.changes
        if change.artifact.id in result.retiring_mise
        and (change.decision in {"skip", "keep"} or change.operation == "detach")
    }
    for change in result.changes:
        artifact = change.artifact
        if change.decision == "skip":
            continue
        if change.operation == "cleanup-settings":
            if retained_mise:
                if retained_mise - {"skip"}:
                    seeded_keys.difference_update(change.setting_keys)
                continue
            updated = update_mise(mise_text, change)
            if updated != mise_text:
                mise_text = updated
                writes["mise.toml"] = updated.encode()
            seeded_keys.difference_update(change.setting_keys)
            continue
        if change.decision == "keep" or change.operation == "detach":
            excluded.add(artifact.exclusion_key)
            if artifact.kind in {"file", "symlink", "block"}:
                excluded_paths.add(artifact.path)
            records.pop(artifact.id, None)
            continue
        if change.operation == "forget":
            records.pop(artifact.id, None)
            continue
        if artifact.kind == "block":
            if change.operation != "adopt":
                snapshot = result.snapshots.get(artifact.path)
                assert not isinstance(snapshot, str)
                assert not isinstance(change.after, str)
                writes[artifact.path] = file_blocks.replace(snapshot, change.after)
        elif artifact.kind in {"file", "symlink"}:
            if change.operation != "adopt":
                writes[artifact.path] = change.after
        else:
            before_keys = (
                mise.setting_keys(mise.parse(mise_text)) if artifact.kind == "defaults" else set()
            )
            mise_text = update_mise(mise_text, change)
            if artifact.kind == "defaults":
                seeded_keys.update(mise.setting_keys(mise.parse(mise_text)) - before_keys)
            writes["mise.toml"] = mise_text.encode()
        excluded_paths.discard(artifact.path)
        if not any(PurePosixPath(path).name == artifact.exclusion_key for path in excluded_paths):
            excluded.discard(artifact.exclusion_key)
        if change.after is None:
            records.pop(artifact.id, None)
        else:
            records[artifact.id] = {
                "path": artifact.path,
                "kind": artifact.kind,
                "key": artifact.key,
                "sha256": digest(
                    change.after if change.state_baseline is None else change.state_baseline
                ),
                "once": artifact.once,
            }
    selection["excluded"] = sorted(excluded)
    if excluded_paths or "excluded_paths" in state:
        state["excluded_paths"] = sorted(excluded_paths)
    if result.box_version is not None and all(
        change.decision != "skip" for change in result.changes
    ):
        document["box_version"] = result.box_version
    if seeded_keys or "seeded_mise_keys" in state:
        state["seeded_mise_keys"] = [list(key) for key in sorted(seeded_keys)]
    if "mise.toml" in writes:
        mise.parse(mise_text)
    writes[CONFIG] = tomlkit.dumps(document).encode()
    for name, before in result.snapshots.items():
        path = (
            result.root / CONFIG
            if name == CONFIG
            else safe_path(result.root, name, allow_link=name != "mise.toml")
        )
        if read_entry(path) != before:
            raise KitFlowError(f"{name} changed after planning; run the command again")
    changed = []
    directories = []
    modes = {}
    try:
        for name, content in writes.items():
            path = (
                result.root / CONFIG
                if name == CONFIG
                else safe_path(result.root, name, allow_link=name != "mise.toml")
            )
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                directories.append(parent)
            modes[name] = (
                path.stat().st_mode & 0o777 if not path.is_symlink() and path.exists() else None
            )
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
