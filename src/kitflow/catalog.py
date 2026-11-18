"""Declarative components and deterministic template composition."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

CURRENT_SCHEMA = 4


class KitFlowError(Exception):
    """An actionable configuration or safety error."""


def known_fields(value, allowed: set[str], location: str):
    if not isinstance(value, dict):
        raise KitFlowError(f"{location} must be a table")
    unknown = set(value) - allowed
    if unknown:
        raise KitFlowError(f"Unknown fields in {location}: {', '.join(sorted(unknown))}")


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
    if parts[0] in {".git", ".venv"} or name == "kitflow.toml":
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


def box_number(root: Path, name: str) -> int:
    path = safe_path(root, name)
    if not path.exists():
        return 0
    if not path.is_file():
        raise KitFlowError(f"Box {name} must be a regular file")
    value = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise KitFlowError(f"Box {name} must contain a positive integer")
    return int(value)


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
    additions: tuple[bytes, ...] | None = None
    directory_var: str = ""
    alternatives: tuple[str, ...] = ()


class Catalog:
    def __init__(self, root: Path, *, standard: Path | None = None):
        self.root = root.resolve()
        default = safe_path(self.root, "default")
        self.standard = (
            standard if standard is not None else (default if default.exists() else None)
        )
        version_root = self.standard or self.root
        self.version = box_number(version_root, ".version")
        self.required_migration = box_number(version_root, ".migration")
        try:
            from kitflow.layers import load_data

            self.data, self.sources = load_data(self.root, self.standard)
            if self.data.get("schema") not in {1, 2, 3, 4}:
                raise KitFlowError("Unsupported catalog schema; expected 1, 2, 3 or 4")
            for _, data in self.sources:
                self.validate(data)
            self.validate(self.data)
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
            from kitflow.wizard import validate_wizard

            validate_wizard(self)
            for section in ("files", "tasks"):
                for row in self.data.get(section, []):
                    self.enabled(row, set(self.components))
                    if "when_not" in row:
                        if section == "files":
                            list(self.file_templates(row))
                        else:
                            self.template(row["template"])
                    for addition in row.get("additions", []):
                        self.enabled(addition, set(self.components))
                        from kitflow.manifests import render_manifest

                        empty = b"{}" if row["path"].endswith(".json") else b""
                        render_manifest(row["path"], empty, (self.template(addition["template"]),))
            self.render(list(self.components), check_conflicts=False)
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise KitFlowError(f"Invalid catalog: {error}") from error

    def validate(self, data: dict):
        required = {
            "components": ("id", "label", "category"),
            "files": ("id", "path"),
            "tasks": ("name", "template"),
            "env": ("name", "value"),
            "defaults": ("id", "template"),
        }
        for section, fields in required.items():
            rows = data.get(section, [])
            if not isinstance(rows, list):
                raise KitFlowError(f"{section} must be an array of tables")
            for row in rows:
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(k), str) for k in fields
                ):
                    raise KitFlowError(
                        f"{section} entries require string fields: {', '.join(fields)}"
                    )
                for name in ("requires", "conflicts", "when", "when_any", "when_not"):
                    value = row.get(name, [])
                    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                        raise KitFlowError(f"{section}.{name} must be an array of component IDs")
                if section == "files" and row.get("mode", "managed") not in {
                    "managed",
                    "once",
                    "block",
                }:
                    raise KitFlowError("File mode must be managed, once or block")
                if section == "files":
                    alternatives = row.get("alternatives", [])
                    if (
                        not isinstance(alternatives, list)
                        or any(
                            not isinstance(name, str)
                            or not re.fullmatch(r"[a-zA-Z0-9_.-]+(?:#[a-zA-Z0-9_-]+)?", name)
                            or name.partition("#")[0] in {".", ".."}
                            for name in alternatives
                        )
                        or (alternatives and row.get("mode") != "once")
                    ):
                        raise KitFlowError("File alternatives require creation-only sibling names")
                    if "directory_var" in row and (
                        not isinstance(row["directory_var"], str)
                        or not re.fullmatch(r"[a-z][a-z0-9_]*", row["directory_var"])
                        or row.get("mode") != "once"
                        or "template" not in row
                    ):
                        raise KitFlowError(
                            "directory_var requires a named variable and a creation-only template"
                        )
                    if "additions" in row:
                        additions = row["additions"]
                        if (
                            row.get("mode") != "once"
                            or not row["path"].endswith((".json", ".toml"))
                            or "template" not in row
                            or not isinstance(additions, list)
                            or any(
                                not isinstance(entry, dict)
                                or set(entry) - {"template", "when", "when_any", "when_not"}
                                or not isinstance(entry.get("template"), str)
                                for entry in additions
                            )
                        ):
                            raise KitFlowError(
                                "Manifest additions require a creation-only JSON or TOML template and conditional templates"
                            )
                    sources = sum(key in row for key in ("template", "empty", "fragments"))
                    if sources != 1:
                        raise KitFlowError(
                            "Files require exactly one of template, empty or fragments"
                        )
                    if "fragments" in row:
                        fragments = row["fragments"]
                        if not isinstance(fragments, list) or not fragments:
                            raise KitFlowError("File fragments must be a nonempty array")
                        if row.get("format") not in {None, "dotenv"}:
                            raise KitFlowError("Composed file format must be dotenv or omitted")
                        for fragment in fragments:
                            if not isinstance(fragment, dict) or set(fragment) - {
                                "template",
                                "when",
                                "when_any",
                            }:
                                raise KitFlowError(
                                    "File fragments accept template, when and when_any"
                                )
                            if not isinstance(fragment.get("template"), str):
                                raise KitFlowError("File fragments require a template")
                            for key in ("when", "when_any"):
                                values = fragment.get(key, [])
                                if not isinstance(values, list) or any(
                                    not isinstance(x, str) for x in values
                                ):
                                    raise KitFlowError(
                                        "Fragment conditions must be arrays of component IDs"
                                    )
                        continue
                    if "format" in row:
                        raise KitFlowError("File format requires fragments")
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
        alternatives = row.get("when_any", [])
        if not isinstance(alternatives, list) or any(
            x not in self.components for x in alternatives
        ):
            raise KitFlowError("Artifact alternatives must reference known components")
        excluded = row.get("when_not", [])
        if not isinstance(excluded, list) or any(x not in self.components for x in excluded):
            raise KitFlowError("Artifact exclusions must reference known components")
        return (
            set(required).issubset(selected)
            and (not alternatives or bool(set(alternatives) & selected))
            and not selected.intersection(excluded)
        )

    def source_path(self, name: str, *, allow_link: bool = False) -> Path:
        user = safe_path(self.root, name, allow_link=allow_link)
        if user.exists() or user.is_symlink() or self.standard is None:
            return user
        # A user file shadows a standard directory and everything below it.
        for parent in user.parents:
            if parent == self.root:
                break
            if parent.exists() and not parent.is_dir():
                return user
        return safe_path(self.standard, name, allow_link=allow_link)

    def source_entries(self, name: str) -> dict[str, Path]:
        entries = {}
        user = safe_path(self.root, name)
        if user.exists() and not user.is_dir():
            raise KitFlowError(f"Not a directory: {user}")
        if self.standard is not None:
            directory = safe_path(self.standard, name, allow_link=True)
            if directory.is_dir() and not directory.is_symlink():
                entries.update((entry.name, entry) for entry in directory.iterdir())
            elif directory.exists() and not user.is_dir():
                raise KitFlowError(f"Not a directory: {directory}")
        if user.exists():
            entries.update((entry.name, entry) for entry in user.iterdir())
        return dict(sorted(entries.items()))

    def template(self, name: str) -> bytes:
        return self.source_path(name).read_bytes()

    @staticmethod
    def link_target(path: Path) -> str:
        target = os.readlink(path)
        if Path(target).is_absolute():
            raise KitFlowError(f"Only relative symbolic links are supported: {path}")
        return target

    def file_templates(self, row: dict) -> list[tuple[str, str, Path | None]]:
        """Expand a directory into stable file IDs, including hidden entries."""
        if row.get("empty") is True or "fragments" in row:
            return [(row["id"], row["path"], None)]
        source = self.source_path(row["template"], allow_link=True)
        if source.is_symlink():
            self.link_target(source)
            return [(row["id"], row["path"], source)]
        if not source.is_dir():
            if not source.is_file():
                raise KitFlowError(f"Template is not a regular file: {source}")
            return [(row["id"], row["path"], source)]
        result = []

        def visit(name: str, relative: str = ""):
            for entry_name in self.source_entries(name):
                if entry_name == ".DS_Store":
                    continue
                child_name = f"{name}/{entry_name}"
                entry = self.source_path(child_name, allow_link=True)
                child = f"{relative}/{entry_name}" if relative else entry_name
                if entry.is_symlink():
                    self.link_target(entry)
                elif entry.is_dir():
                    visit(child_name, child)
                    continue
                elif not entry.is_file():
                    raise KitFlowError(f"Template is not a regular file: {entry}")
                result.append((f"{row['id']}/{child}", f"{row['path']}/{child}", entry))

        visit(row["template"])
        return result

    def compose_file(self, row: dict, chosen: set[str], *, check_duplicates=True) -> bytes:
        parts = []
        variables = set()
        for fragment in row["fragments"]:
            if not self.enabled(fragment, chosen):
                continue
            text = self.template(fragment["template"]).decode("utf-8").strip("\r\n")
            if row.get("format") == "dotenv" and check_duplicates:
                for line in text.splitlines():
                    match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
                    if match:
                        name = match[1]
                        if name in variables:
                            raise KitFlowError(
                                f"Duplicate environment variable {name} in {row['path']}"
                            )
                        variables.add(name)
            if text:
                parts.append(text)
        return ("\n\n".join(parts) + "\n" if parts else "").encode("utf-8")

    def render(self, selected: list[str], *, check_conflicts: bool = True) -> dict[str, Artifact]:
        chosen = set(self.resolve(selected, check_conflicts=check_conflicts))
        result = {}
        paths = set()
        file_ids = set()
        for row in self.data.get("files", []):
            if not self.enabled(row, chosen):
                continue
            if (
                row.get("mode") == "block"
                and "template" in row
                and self.source_path(row["template"], allow_link=True).is_dir()
            ):
                raise KitFlowError("Block mode does not support directory templates")
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
                kind = "symlink" if is_link else "file"
                content = (
                    self.compose_file(row, chosen, check_duplicates=check_conflicts)
                    if "fragments" in row
                    else b""
                )
                if source is not None:
                    content = self.link_target(source) if is_link else source.read_bytes()
                if row.get("mode") == "block":
                    from kitflow import file_blocks

                    if is_link or file_id != identity:
                        raise KitFlowError(
                            "Block mode requires one regular text file, not a directory or link"
                        )
                    assert isinstance(content, bytes)
                    content = content.rstrip(b"\r\n") + b"\n" if content else b""
                    file_blocks.wrap(content)
                    kind = "block"
                if ("directory_var" in row or row.get("alternatives")) and (
                    is_link or file_id != identity
                ):
                    raise KitFlowError(
                        "Directory variables and alternatives require one regular file"
                    )
                additions = None
                if "additions" in row:
                    if is_link or file_id != identity:
                        raise KitFlowError("Manifest additions require one regular file")
                    additions = tuple(
                        self.template(entry["template"])
                        for entry in row["additions"]
                        if self.enabled(entry, chosen)
                    )
                result[file_id] = Artifact(
                    file_id,
                    target,
                    content,
                    row.get("mode") == "once",
                    kind=kind,
                    additions=additions,
                    directory_var=row.get("directory_var", ""),
                    alternatives=tuple(row.get("alternatives", [])),
                )
        for row in self.data.get("defaults", []):
            if self.enabled(row, chosen):
                from kitflow.mise import missing_defaults

                content = self.template(row["template"])
                missing_defaults("", content)
                identity = f"defaults.{row['id']}"
                result[identity] = Artifact(identity, "mise.toml", content, True, "defaults")
        tasks: dict[str, list[str]] = {}
        metadata: dict[str, dict] = {}
        for row in self.data.get("tasks", []):
            if self.enabled(row, chosen):
                fragment = self.template(row["template"]).decode().strip()
                directory = row.get("directory_env")
                if directory is not None:
                    if not isinstance(directory, str) or not re.fullmatch(
                        r"[A-Za-z_][A-Za-z0-9_]*", directory
                    ):
                        raise KitFlowError("directory_env must be an environment variable name")
                    fragment = (
                        f'(\ncd "${{{directory}:?Set {directory} in mise.toml}}"\n{fragment}\n)'
                    )
                tasks.setdefault(row["name"], []).append(fragment)
                options = metadata.setdefault(row["name"], {})
                for key in ("description", "alias", "usage", "hide", "quiet"):
                    if key not in row:
                        continue
                    value = row[key]
                    expected = bool if key in {"hide", "quiet"} else str
                    if type(value) is not expected:
                        raise KitFlowError(f"tasks.{key} must be {expected.__name__}")
                    if key in options and options[key] != value:
                        raise KitFlowError(f"Conflicting task metadata: {row['name']}.{key}")
                    options[key] = value
        for name, fragments in tasks.items():
            if not re.fullmatch(r"[a-zA-Z0-9_:-]+", name):
                raise KitFlowError(f"Invalid task name: {name}")
            script = "set -eu\n" + "\n".join(fragments) + "\n"
            if "'''" in script:
                raise KitFlowError(f"Triple single quote in task: {name}")
            options = "".join(
                f"{key} = {json.dumps(value)}\n" for key, value in metadata[name].items()
            )
            content = f"[tasks.\"{name}\"]\n{options}run = '''\n{script}'''\n"
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
