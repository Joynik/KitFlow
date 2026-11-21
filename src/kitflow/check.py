"""Read-only validation of box definitions and connected project configuration."""

import itertools
import json
import re
import tomllib
from pathlib import Path

from kitflow import mise
from kitflow.box_layout import layer_paths
from kitflow.catalog import Artifact, Catalog, KitFlowError, known_fields, safe_path
from kitflow.engine import (
    CONFIG,
    is_excluded,
    load_config,
    plan,
    read_file,
    resolve_file_directories,
)

BOX_FIELDS = {
    "steps": {"id", "label", "categories", "description", "order", "when", "when_any"},
    "components": {
        "id",
        "label",
        "category",
        "description",
        "requires",
        "conflicts",
        "recommended",
        "when",
        "when_any",
    },
    "files": {
        "id",
        "path",
        "template",
        "when",
        "when_any",
        "when_not",
        "mode",
        "empty",
        "fragments",
        "additions",
        "directory_var",
        "alternatives",
        "format",
        "mise_defaults",
    },
    "tasks": {
        "id",
        "name",
        "template",
        "preamble",
        "when",
        "when_any",
        "when_not",
        "directory_env",
        "description",
        "alias",
        "usage",
        "hide",
        "quiet",
    },
    "env": {"id", "name", "value", "when", "when_any"},
    "defaults": {"id", "template", "when", "when_any", "example_section"},
}


def validate_box(root: Path, *, standard: Path | None = None) -> Catalog:
    from kitflow.box_layout import layer_paths, resolve_layer
    from kitflow.layers import load_data

    personal, installed = layer_paths(root)
    standard = standard if standard is not None else installed
    if standard is not None:
        standard = resolve_layer(standard)
    _, sources = load_data(resolve_layer(personal), standard)
    for source, data in sources:
        known_fields(data, {"schema", "disabled", *BOX_FIELDS}, str(source / "kitflow-box.toml"))
        for section, allowed in BOX_FIELDS.items():
            rows = data.get(section, [])
            if not isinstance(rows, list):
                raise KitFlowError(f"{section} must be an array of tables")
            for index, row in enumerate(rows, 1):
                location = f"{source}: {section}[{index}]"
                known_fields(row, allowed, location)
                if "description" in row and not isinstance(row["description"], str):
                    raise KitFlowError(f"{location}.description must be a string")
                if "empty" in row and type(row["empty"]) is not bool:
                    raise KitFlowError(f"{location}.empty must be a boolean")
    return Catalog(root, standard=standard)


def load_validation_rules(root: Path) -> dict[str, str]:
    path = safe_path(root, "validation.toml")
    content = read_file(path)
    if content is None:
        return {}
    data = tomllib.loads(content.decode("utf-8"))
    known_fields(data, {"files"}, str(path))
    rules = data.get("files", {})
    if not isinstance(rules, dict):
        raise KitFlowError("[files] must be a table")
    for name, mode in rules.items():
        safe_path(root, name, allow_link=True)
        if mode not in ("jsonc", "skip"):
            raise KitFlowError(f"Invalid validation mode for {name}: expected jsonc or skip")
    return rules


def template_mode(path: Path, layers: tuple[Path, ...], rules: dict[str, str]) -> str | None:
    for layer in layers:
        if path.is_relative_to(layer):
            return rules.get(path.relative_to(layer).as_posix())
    return None


JSON_STRING = r'"(?:[^"\\]|\\.)*"'
JSONC_COMMENTS = re.compile(rf"{JSON_STRING}|//[^\r\n]*|/\*[\s\S]*?\*/")
JSONC_TRAILING_COMMA = re.compile(rf'{JSON_STRING}|(?<=[\w"\]}}])[ \t\r\n]*,(?=[ \t\r\n]*[\]}}])')


def jsonc_as_json(text: str) -> str:
    # Replace comments with whitespace to preserve token boundaries and error positions.
    text = JSONC_COMMENTS.sub(
        lambda match: re.sub(r"[^\r\n]", " ", match[0]) if match[0].startswith("/") else match[0],
        text,
    )
    # A trailing comma can follow a value, but cannot be the first item.
    return JSONC_TRAILING_COMMA.sub(
        lambda match: match[0][:-1] + " " if match[0].endswith(",") else match[0], text
    )


def validate_syntax(path: Path, suffix: str | None = None, mode: str | None = None):
    if mode == "skip":
        return
    suffix = suffix or path.suffix.lower()
    if (mode != "jsonc" and suffix not in {".toml", ".json"}) or not path.exists():
        return
    content = read_file(path)
    if content is not None:
        text = content.decode("utf-8")
        if mode == "jsonc":
            json.loads(jsonc_as_json(text))
        elif suffix == ".toml":
            tomllib.loads(text)
        else:
            json.loads(text)


def configuration_issues(
    box: Path, project: Path, *, standard: Path | None = None, check_standard: bool = True
) -> list[tuple[Path, str]]:
    issues = []
    personal, installed = layer_paths(box)
    default = standard if standard is not None else installed
    if check_standard and default is not None and default.is_dir():
        directory = default.resolve()
        issues.extend(configuration_issues(directory, directory, check_standard=False))
    catalog = None
    errors = (KitFlowError, OSError, ValueError, TypeError)
    layers = tuple(layer.resolve() for layer in (default, personal) if layer is not None)
    rules = {}
    for layer in layers:
        try:
            rules.update(load_validation_rules(layer))
        except errors as error:
            issues.append((layer / "validation.toml", str(error)))
    try:
        catalog = validate_box(box, standard=standard)
    except errors as error:
        issues.append((box / "kitflow-box.toml", str(error)))
    if catalog is not None:
        checked = set()
        for row in catalog.data.get("files", []):
            if "fragments" in row:
                # Check compatible fragment combinations, including duplicate dotenv keys.
                fragments = row["fragments"]
                conditions = [row, *fragments]
                for condition in conditions:
                    catalog.enabled(condition, set(catalog.components))
                choices = [
                    [*row.get("when", []), *fragment.get("when", []), *([option] if option else [])]
                    for fragment in fragments
                    for option in fragment.get("when_any", []) or [None]
                ]
                for left, right in itertools.combinations_with_replacement(choices, 2):
                    for option in row.get("when_any", []) or [None]:
                        try:
                            selected = catalog.resolve(
                                [*left, *right, *([option] if option else [])]
                            )
                        except KitFlowError:
                            continue
                        try:
                            catalog.compose_file(row, set(selected))
                        except errors as error:
                            issue = (box / "kitflow-box.toml", str(error))
                            if issue not in issues:
                                issues.append(issue)
                continue
            if row.get("empty") is True:
                continue
            for _, output, target in catalog.file_templates(row):
                if target is None or target.is_symlink():
                    continue
                suffix = Path(output).suffix.lower()
                if target.suffix.lower() in {".toml", ".json"}:
                    suffix = target.suffix.lower()
                if (target, suffix) in checked:
                    continue
                checked.add((target, suffix))
                try:
                    validate_syntax(target, suffix, template_mode(target, layers, rules))
                except errors as error:
                    issues.append((target, str(error)))
    if not project.is_dir():
        issues.append((project, "Project directory does not exist"))
        return issues
    if not (project / CONFIG).exists() and not (project / CONFIG).is_symlink():
        return issues
    document = None
    try:
        document = load_config(project)
        if catalog is not None:
            plan(project, catalog, document["selection"].get("components", []), document)
    except errors as error:
        issues.append((project / CONFIG, str(error)))
    if document is not None and catalog is not None:
        try:
            artifacts = catalog.render(document["selection"].get("components", []))
            if any(artifact.directory_var for artifact in artifacts.values()):
                artifacts = resolve_file_directories(
                    project.resolve(), artifacts, read_file(project / "mise.toml")
                )
        except errors:
            artifacts = {}
        excluded = set(document["selection"].get("excluded", []))
        excluded_paths = set(document.get("state", {}).get("excluded_paths", []))
        templates = {
            identity: source
            for row in catalog.data.get("files", [])
            for identity, _, source in catalog.file_templates(row)
        }
        for identity, artifact in artifacts.items():
            if artifact.kind != "file" or is_excluded(artifact, excluded, excluded_paths):
                continue
            try:
                template = templates.get(identity)
                suffix = template.suffix.lower() if template is not None else None
                if suffix not in {".toml", ".json"}:
                    suffix = None
                mode = template_mode(template, layers, rules) if template is not None else None
                validate_syntax(safe_path(project, artifact.path), suffix, mode)
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
    return list(dict.fromkeys(issues))
