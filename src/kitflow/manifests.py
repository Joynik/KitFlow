"""Add missing manifest entries while keeping user-owned values."""

import json
import re
import tomllib
from collections.abc import MutableMapping
from pathlib import PurePosixPath

import tomlkit

from kitflow.catalog import KitFlowError


def requirement_name(requirement: str) -> str:
    match = re.match(r"[a-zA-Z0-9_.-]+", requirement.lstrip())
    return re.sub(r"[-_.]+", "-", match[0]).lower() if match else ""


def add_missing(target, source):
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], MutableMapping) and isinstance(value, dict):
            add_missing(target[key], value)


def render_manifest(path: str, original: bytes, additions: tuple[bytes, ...]) -> bytes:
    json_format = PurePosixPath(path).suffix == ".json"
    try:
        document = json.loads(original) if json_format else tomlkit.parse(original.decode())
        if not isinstance(document, MutableMapping):
            raise ValueError("expected a manifest object")
        for patch in additions:
            data = json.loads(patch) if json_format else tomllib.loads(patch.decode())
            if json_format:
                production = document.get("dependencies", {})
                optional = document.get("optionalDependencies", {})
                dev = data.get("devDependencies", {})
                for name in tuple(dev):
                    if name in production or name in optional:
                        del dev[name]
                if not dev:
                    data.pop("devDependencies", None)
                if "devDependencies" in data and not isinstance(
                    document.get("devDependencies", {}), MutableMapping
                ):
                    raise ValueError("devDependencies must be an object")
            else:
                requirements = data.pop("dependency-groups", {}).get("dev", [])
                if requirements:
                    add_dev_requirements(document, requirements)
                if "workspace" in document and "package" not in document and "package" in data:
                    data["workspace"] = data.pop("package")
            add_missing(document, data)
        if json_format:
            if document == json.loads(original):
                return original
            return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
        return tomlkit.dumps(document).encode()
    except (ValueError, TypeError, AttributeError) as error:
        raise KitFlowError(f"Cannot extend {path}: {error}") from error


def add_dev_requirements(document, requirements):
    groups = document.setdefault("dependency-groups", tomlkit.table())
    dev = groups.setdefault("dev", tomlkit.array())
    if not isinstance(dev, list):
        raise ValueError("dependency-groups.dev must be an array")
    project = document.get("project", {})
    declared = {
        requirement_name(item) for item in project.get("dependencies", []) if isinstance(item, str)
    }
    pending = ["dev"]
    visited = set()
    while pending:
        group = pending.pop()
        if group in visited:
            continue
        visited.add(group)
        for item in groups.get(group, []):
            if isinstance(item, str):
                declared.add(requirement_name(item))
            elif isinstance(item, MutableMapping) and isinstance(item.get("include-group"), str):
                pending.append(item["include-group"])
    for item in requirements:
        name = requirement_name(item)
        if name not in declared:
            dev.append(item)
            declared.add(name)


def has_json_key(content: bytes, key: str) -> bool:
    document = json.loads(content)
    return isinstance(document, dict) and key in document
