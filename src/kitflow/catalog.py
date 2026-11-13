"""Declarative components and deterministic template composition."""

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class KitFlowError(Exception):
    """An actionable configuration or safety error."""


def safe_path(root: Path, name: str, *, allow_link: bool = False) -> Path:
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith("/")
        or ".." in parts
        or "\\" in name
        or str(PurePosixPath(name)) != name
    ):
        raise KitFlowError(f"Unsafe path: {name!r}")
    if parts[0] in {".git", ".beads", ".venv"} or name == "kitflow.toml":
        raise KitFlowError(f"Reserved path: {name}")
    path = root.joinpath(*parts)
    for parent in list(path.parents) if allow_link else [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise KitFlowError(f"Symbolic links are not managed: {name}")
    resolved = path.parent.resolve() if allow_link else path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise KitFlowError(f"Path escapes root: {name}")
    return path


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    category: str
    description: str
    requires: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class Artifact:
    id: str
    path: str
    content: bytes | str
    once: bool = False
    kind: str = "file"
    key: str = ""


class Catalog:
    def __init__(self, root: Path):
        self.root = root.resolve()
        try:
            self.data = tomllib.loads((root / "kitflow-box.toml").read_text())
            if self.data.get("schema") != 1:
                raise KitFlowError("Unsupported catalog schema; expected 1")
            self.validate()
            self.components = {}
            for row in self.data.get("components", []):
                identity = row["id"]
                if not re.fullmatch(r"[a-z][a-z0-9_-]*", identity):
                    raise KitFlowError(f"Invalid component ID: {identity}")
                if identity in self.components:
                    raise KitFlowError(f"Duplicate component: {identity}")
                self.components[identity] = Component(
                    identity,
                    row["label"],
                    row["category"],
                    row.get("description", ""),
                    tuple(row.get("requires", [])),
                    tuple(row.get("conflicts", [])),
                )
            if not self.components:
                raise KitFlowError("Catalog has no components")
            for component in self.components.values():
                for other in (*component.requires, *component.conflicts):
                    if other not in self.components:
                        raise KitFlowError(f"Unknown dependency or conflict: {other}")
            for identity in self.components:
                self.resolve([identity])
            self.render(list(self.components), check_conflicts=False)
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise KitFlowError(f"Invalid catalog: {error}") from error

    def validate(self):
        required = {
            "components": ("id", "label", "category"),
            "files": ("id", "path"),
            "tasks": ("name", "template"),
            "env": ("name", "value"),
        }
        for section, fields in required.items():
            rows = self.data.get(section, [])
            if not isinstance(rows, list):
                raise KitFlowError(f"{section} must be an array of tables")
            for row in rows:
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(k), str) for k in fields
                ):
                    raise KitFlowError(
                        f"{section} entries require string fields: {', '.join(fields)}"
                    )
                for name in ("requires", "conflicts", "when"):
                    value = row.get(name, [])
                    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                        raise KitFlowError(f"{section}.{name} must be an array of component IDs")
                if section == "files" and row.get("mode", "managed") not in {"managed", "once"}:
                    raise KitFlowError("File mode must be managed or once")
                if section == "files":
                    if row.get("empty") is True:
                        if "template" in row or row.get("mode") != "once":
                            raise KitFlowError("Empty files require mode once and no template")
                    elif not isinstance(row.get("template"), str):
                        raise KitFlowError("Files require a template or empty = true")

    def resolve(self, selected: list[str], *, check_conflicts: bool = True) -> list[str]:
        resolved: set[str] = set()
        visiting: set[str] = set()

        def visit(identity: str):
            if identity not in self.components:
                raise KitFlowError(f"Unknown component: {identity}")
            if identity in visiting:
                raise KitFlowError(f"Dependency cycle: {identity}")
            if identity in resolved:
                return
            visiting.add(identity)
            for dependency in self.components[identity].requires:
                visit(dependency)
            visiting.remove(identity)
            resolved.add(identity)

        for identity in selected:
            visit(identity)
        if check_conflicts:
            for identity in resolved:
                collisions = resolved.intersection(self.components[identity].conflicts)
                if collisions:
                    raise KitFlowError(f"{identity} conflicts with {', '.join(sorted(collisions))}")
        return [identity for identity in self.components if identity in resolved]

    def enabled(self, row: dict, selected: set[str]) -> bool:
        required = row.get("when", [])
        if not isinstance(required, list) or any(x not in self.components for x in required):
            raise KitFlowError("Artifact conditions must reference known components")
        return set(required).issubset(selected)

    def template(self, name: str) -> bytes:
        return safe_path(self.root, name).read_bytes()

    @staticmethod
    def link_target(path: Path) -> str:
        target = os.readlink(path)
        if Path(target).is_absolute():
            raise KitFlowError(f"Only relative symbolic links are supported: {path}")
        return target

    def file_templates(self, row: dict) -> list[tuple[str, str, Path | None]]:
        """Expand a directory into stable file IDs, including hidden entries."""
        if row.get("empty") is True:
            return [(row["id"], row["path"], None)]
        source = safe_path(self.root, row["template"], allow_link=True)
        if source.is_symlink():
            self.link_target(source)
            return [(row["id"], row["path"], source)]
        if not source.is_dir():
            if not source.is_file():
                raise KitFlowError(f"Template is not a regular file: {source}")
            return [(row["id"], row["path"], source)]
        result = []

        def visit(directory: Path):
            for entry in sorted(directory.iterdir()):
                safe_path(self.root, entry.relative_to(self.root).as_posix(), allow_link=True)
                if entry.is_symlink():
                    self.link_target(entry)
                    relative = entry.relative_to(source).as_posix()
                    result.append((f"{row['id']}/{relative}", f"{row['path']}/{relative}", entry))
                elif entry.is_dir():
                    visit(entry)
                elif entry.is_file():
                    relative = entry.relative_to(source).as_posix()
                    result.append((f"{row['id']}/{relative}", f"{row['path']}/{relative}", entry))
                else:
                    raise KitFlowError(f"Template is not a regular file: {entry}")

        visit(source)
        return result

    def render(self, selected: list[str], *, check_conflicts: bool = True) -> dict[str, Artifact]:
        chosen = set(self.resolve(selected, check_conflicts=check_conflicts))
        result = {}
        paths = set()
        file_ids = set()
        for row in self.data.get("files", []):
            if not self.enabled(row, chosen):
                continue
            identity, path = row["id"], row["path"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", identity) or identity in file_ids:
                raise KitFlowError(f"Invalid or duplicate file ID: {identity}")
            file_ids.add(identity)
            safe_path(self.root, path, allow_link=True)
            if path == "mise.toml":
                raise KitFlowError(f"Duplicate or reserved file target: {path}")
            for file_id, target, source in self.file_templates(row):
                safe_path(self.root, target, allow_link=True)
                if target == "mise.toml" or any(
                    target == existing
                    or PurePosixPath(target) in PurePosixPath(existing).parents
                    or PurePosixPath(existing) in PurePosixPath(target).parents
                    for existing in paths
                ):
                    raise KitFlowError(f"Duplicate or reserved file target: {target}")
                paths.add(target)
                is_link = source is not None and source.is_symlink()
                content = b""
                if source is not None:
                    content = self.link_target(source) if is_link else source.read_bytes()
                result[file_id] = Artifact(
                    file_id,
                    target,
                    content,
                    row.get("mode") == "once",
                    kind="symlink" if is_link else "file",
                )
        tasks: dict[str, list[str]] = {}
        for row in self.data.get("tasks", []):
            if self.enabled(row, chosen):
                tasks.setdefault(row["name"], []).append(
                    self.template(row["template"]).decode().strip()
                )
        for name, fragments in tasks.items():
            if not re.fullmatch(r"[a-zA-Z0-9_:-]+", name):
                raise KitFlowError(f"Invalid task name: {name}")
            script = "set -eu\n" + "\n".join(fragments) + "\n"
            if "'''" in script:
                raise KitFlowError(f"Triple single quote in task: {name}")
            content = f"[tasks.\"{name}\"]\nrun = '''\n{script}'''\n"
            identity = f"task.{name}"
            result[identity] = Artifact(
                identity, "mise.toml", content.encode(), kind="task", key=name
            )
        for row in self.data.get("env", []):
            if self.enabled(row, chosen):
                name = row["name"]
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise KitFlowError(f"Invalid environment key: {name}")
                identity = f"env.{name}"
                if identity in result:
                    raise KitFlowError(f"Duplicate environment key: {name}")
                result[identity] = Artifact(
                    identity,
                    "mise.toml",
                    f"{name} = {json.dumps(row['value'])}\n".encode(),
                    kind="env",
                    key=name,
                )
        return result
