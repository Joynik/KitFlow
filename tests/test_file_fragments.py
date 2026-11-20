"""Conditional text composition uses the existing managed-file lifecycle."""

from pathlib import Path

import pytest

from kitflow.catalog import Catalog, KitFlowError
from kitflow.check import configuration_issues
from kitflow.engine import apply, load_config, plan


def box(tmp_path: Path) -> Path:
    root = tmp_path / "box"
    root.mkdir()
    (root / "base.txt").write_text("# General\nBASE=one\n\n")
    (root / "extra.txt").write_text("# Extra\nEXTRA=two\n")
    (root / "kitflow-box.toml").write_text("""schema = 4
[[components]]
id = "base"
label = "Base"
category = "Languages"
[[components]]
id = "extra"
label = "Extra"
category = "Tools"
[[files]]
id = "example"
path = ".env.example"
format = "dotenv"
fragments = [
  { template = "base.txt" },
  { template = "extra.txt", when = ["extra"] },
]
""")
    return root


def test_conditional_composition_update_conflict_and_removal(tmp_path):
    root = box(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    catalog = Catalog(root)
    apply(plan(project, catalog, ["base"], load_config(project)), {})
    target = project / ".env.example"
    assert target.read_bytes() == b"# General\nBASE=one\n"
    update = plan(project, catalog, ["base", "extra"], load_config(project))
    assert not update.changes[0].conflict
    apply(update, {})
    assert target.read_bytes() == b"# General\nBASE=one\n\n# Extra\nEXTRA=two\n"
    target.write_text(target.read_text() + "PERSONAL=three\n")
    update = plan(project, catalog, ["base"], load_config(project))
    assert update.changes[0].conflict
    assert "PERSONAL" in target.read_text()


def test_dotenv_duplicates_are_reported_by_render_and_check(tmp_path):
    root = box(tmp_path)
    (root / "extra.txt").write_text("export BASE=two\n")
    catalog = Catalog(root)
    assert catalog.render(["base"])["example"].content == b"# General\nBASE=one\n"
    with pytest.raises(KitFlowError, match="Duplicate environment variable BASE"):
        catalog.render(["extra"])
    assert any(
        "Duplicate environment variable BASE" in message
        for _, message in configuration_issues(root, tmp_path)
    )


def test_mutually_exclusive_dotenv_fragments_do_not_conflict(tmp_path):
    root = box(tmp_path)
    manifest = root / "kitflow-box.toml"
    text = manifest.read_text().replace(
        'category = "Languages"', 'category = "Languages"\nconflicts = ["extra"]'
    )
    text = text.replace('{ template = "base.txt" }', '{ template = "base.txt", when = ["base"] }')
    manifest.write_text(text)
    (root / "extra.txt").write_text("BASE=two\n")
    assert not configuration_issues(root, tmp_path)


@pytest.mark.parametrize(
    "fragment",
    [
        '{ template = "base.txt", typo = true }',
        '{ template = "base.txt", when = "extra" }',
        '{ template = "base.txt", when = ["missing"] }',
        '{ template = "../outside.txt" }',
    ],
)
def test_invalid_fragments_are_rejected(tmp_path, fragment):
    root = box(tmp_path)
    manifest = root / "kitflow-box.toml"
    manifest.write_text(manifest.read_text().replace('{ template = "base.txt" }', fragment))
    with pytest.raises(KitFlowError):
        Catalog(root)


def test_fragment_overlay_and_binary_directory_templates_coexist(tmp_path):
    root = box(tmp_path)
    standard = root / "standard"
    personal = root / "personal"
    personal.mkdir()
    standard.mkdir()
    for name in ("kitflow-box.toml", "base.txt", "extra.txt"):
        (root / name).rename(standard / name)
    (personal / "kitflow-box.toml").write_text("""schema = 4
[[files]]
id = "folder"
path = ".editor"
template = "templates/editor"
""")
    (personal / "base.txt").write_text("BASE=user\n")
    directory = personal / "templates/editor/.nested"
    directory.mkdir(parents=True)
    (directory / "binary.pdf").write_bytes(b"\x00\xff\x01")
    (directory / "link").symlink_to("binary.pdf")
    artifacts = Catalog(root).render(["base"])
    assert artifacts["example"].content == b"BASE=user\n"
    assert artifacts["folder/.nested/binary.pdf"].content == b"\x00\xff\x01"
    assert artifacts["folder/.nested/link"].content == "binary.pdf"


def test_existing_once_file_can_become_managed_and_conditional(tmp_path):
    root = box(tmp_path)
    manifest = root / "kitflow-box.toml"
    assembled = manifest.read_text()
    legacy = (
        assembled[: assembled.index("[[files]]")]
        + """[[files]]
id = "example"
path = ".env.example"
template = "base.txt"
mode = "once"
"""
    )
    manifest.write_text(legacy)
    project = tmp_path / "project"
    project.mkdir()
    apply(plan(project, Catalog(root), ["base"], load_config(project)), {})
    manifest.write_text(
        assembled.replace('format = "dotenv"', 'when = ["extra"]\nformat = "dotenv"')
    )
    update = plan(project, Catalog(root), ["extra"], load_config(project))
    assert not update.changes[0].conflict
    apply(update, {})
    assert "EXTRA=two" in (project / ".env.example").read_text()
    update = plan(project, Catalog(root), ["base"], load_config(project))
    assert update.changes[0].operation == "delete"
    apply(update, {})
    assert not (project / ".env.example").exists()
