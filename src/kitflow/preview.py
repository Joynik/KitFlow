"""Render selected Box content without touching installed project files."""

from pathlib import Path

from kitflow import file_blocks, manifests, mise
from kitflow.catalog import Catalog, KitFlowError
from kitflow.engine import CONFIG, parse_config, read_file


def preview(
    root: Path, box: Path, components: str | None, kind: str | None, target: str | None
) -> bytes:
    if kind in {"defaults", "files", "tasks", "components"}:
        if target is not None:
            raise KitFlowError(f"show {kind} takes no target")
    elif kind not in {"task", "file"} or not target:
        raise KitFlowError(
            "Use show task NAME, show file PATH, show defaults, files, tasks or components"
        )
    if components is None:
        snapshot = read_file(root / CONFIG)
        if snapshot is None and kind != "components":
            raise KitFlowError("Run kitflow init first or pass --components")
        selected = parse_config(root, snapshot)["selection"]["components"]
    else:
        selected = [item.strip() for item in components.split(",") if item.strip()]
    if not box.is_dir():
        raise KitFlowError("Local Box not found; run kitflow first or pass --box")
    catalog = Catalog(box)
    if kind == "components":
        active = set(catalog.resolve(selected))
        return "".join(
            f"{identity}\t{'selected' if identity in active else 'available'}\t{component.label}\n"
            for identity, component in catalog.components.items()
        ).encode()
    artifacts = catalog.render(selected)
    if kind == "tasks":
        return "".join(
            f"{artifact.key}\n" for artifact in artifacts.values() if artifact.kind == "task"
        ).encode()
    files = {
        artifact.path: artifact
        for artifact in artifacts.values()
        if artifact.kind in {"file", "block", "symlink"}
    }
    if kind == "files":
        return "".join(f"{path}\n" for path in sorted({*files, "mise.toml"})).encode()
    if kind == "defaults" or (kind == "file" and target == "mise.toml"):
        text = ""
        for artifact in artifacts.values():
            if artifact.kind == "defaults":
                assert isinstance(artifact.content, bytes)
                text = mise.add_defaults(text, artifact.content)
        for artifact in artifacts.values():
            if artifact.kind == "env" or (kind == "file" and artifact.kind == "task"):
                assert isinstance(artifact.content, bytes)
                if kind == "file":
                    text = mise.replace(text, artifact, artifact.content)
                else:
                    text = mise.add_defaults(text, b"[env]\n" + artifact.content)
        return text.encode()
    if kind == "task":
        artifact = artifacts.get(f"task.{target}")
    else:
        assert target is not None
        artifact = files.get(target)
    if artifact is None:
        raise KitFlowError(f"No generated {kind} for the selected components: {target}")
    content = artifact.content
    if isinstance(content, str):
        return f"symlink -> {content}\n".encode()
    if artifact.kind == "block":
        return file_blocks.wrap(content)
    if artifact.additions:
        return manifests.render_manifest(artifact.path, content, artifact.additions)
    return content
