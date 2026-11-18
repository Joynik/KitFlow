"""Managed text spans preserve user bytes and require intact ownership markers."""

import pytest

from kitflow import file_blocks
from kitflow.catalog import Catalog, KitFlowError
from kitflow.check import configuration_issues
from kitflow.engine import apply, load_config, plan


@pytest.fixture
def box(tmp_path):
    root = tmp_path / "box"
    root.mkdir()
    (root / "rules.txt").write_text("# General\n*.tmp\n")
    (root / "kitflow-box.toml").write_text("""schema=4
[[components]]
id="language"
label="Language"
category="Languages"
[[files]]
id="ignore"
path=".gitignore"
template="rules.txt"
mode="block"
when=["language"]
""")
    return root


def update(project, box, selected=None):
    return plan(
        project, Catalog(box), ["language"] if selected is None else selected, load_config(project)
    )


def test_block_updates_preserve_user_and_surrounding_bytes(box, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    apply(update(project, box), {})
    path = project / ".gitignore"
    assert path.read_bytes() == file_blocks.wrap(b"# General\n*.tmp\n") + file_blocks.USER
    original = path.read_bytes().replace(b"# </user>", b"personal/\r\n!keep.tmp\r\n# </user>")
    prefix, suffix = b"# Before\r\n", b"# After\r\n\xff"
    path.write_bytes(prefix + original + suffix)
    (box / "rules.txt").write_text("# General\n*.log\n")
    result = update(project, box)
    assert len(result.changes) == 1
    assert not result.changes[0].conflict
    assert b"personal/" not in result.changes[0].before
    apply(result, {})
    assert path.read_bytes() == prefix + original.replace(b"*.tmp", b"*.log") + suffix
    assert not update(project, box).changes
    assert not configuration_issues(box, project)
    result = update(project, box, [])
    assert result.changes[0].operation == "remove-block"
    apply(result, {})
    assert path.read_bytes() == prefix + original[original.index(b"\n# <user>") :] + suffix


def test_modified_owned_content_is_replaced_without_conflict_or_diff(box, tmp_path, capsys):
    from kitflow.cli import show_diff

    project = tmp_path / "project"
    project.mkdir()
    apply(update(project, box), {})
    path = project / ".gitignore"
    path.write_bytes(path.read_bytes().replace(b"*.tmp", b"personal-edit/"))
    (box / "rules.txt").write_text("*.log\n")
    result = update(project, box)
    assert not result.changes[0].conflict
    assert result.changes[0].decision == "apply"
    show_diff(result.changes[0])
    assert capsys.readouterr().out == ""
    apply(result, {})
    owned = file_blocks.span(path.read_bytes())
    assert owned is not None
    assert owned[2] == b"*.log\n"
    assert path.read_bytes().endswith(file_blocks.USER)


@pytest.mark.parametrize("damage", ["both", "begin", "end", "duplicate", "reversed", "nested"])
def test_missing_or_damaged_markers_detach_without_writing(box, tmp_path, damage):
    project = tmp_path / "project"
    project.mkdir()
    apply(update(project, box), {})
    path = project / ".gitignore"
    original = path.read_bytes()
    if damage in {"both", "begin"}:
        original = original.replace(b"# <kitflow>\n", b"")
    if damage in {"both", "end"}:
        original = original.replace(b"# </kitflow>\n", b"")
    if damage == "duplicate":
        original += file_blocks.wrap(b"another/\n")
    if damage == "reversed":
        original = b"# </kitflow>\n# <kitflow>\n"
    if damage == "nested":
        original = original.replace(b"*.tmp", b"# <user>\n*.tmp")
    path.write_bytes(original)
    result = update(project, box)
    assert result.changes[0].operation == "detach"
    apply(result, {})
    assert path.read_bytes() == original
    assert ".gitignore" in load_config(project)["selection"]["excluded"]
    assert not update(project, box).changes


@pytest.mark.parametrize("legacy_managed", [False, True])
def test_existing_unmarked_file_is_never_wrapped_or_replaced(box, tmp_path, legacy_managed):
    project = tmp_path / "project"
    project.mkdir()
    manifest = box / "kitflow-box.toml"
    if legacy_managed:
        manifest.write_text(manifest.read_text().replace('mode="block"', 'mode="managed"'))
        apply(update(project, box), {})
        manifest.write_text(manifest.read_text().replace('mode="managed"', 'mode="block"'))
    path = project / ".gitignore"
    path.write_bytes(b"# My rules\nprivate/\n")
    result = update(project, box)
    assert result.changes[0].operation == "detach"
    apply(result, {})
    assert path.read_bytes() == b"# My rules\nprivate/\n"


def test_concurrent_user_edit_aborts_before_replacing_any_block(box, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    apply(update(project, box), {})
    (box / "rules.txt").write_text("new/\n")
    result = update(project, box)
    path = project / ".gitignore"
    path.write_bytes(path.read_bytes() + b"new-user-rule/\n")
    original = path.read_bytes()
    with pytest.raises(KitFlowError, match="changed after planning"):
        apply(result, {})
    assert path.read_bytes() == original


@pytest.mark.parametrize("source", ["directory", "link", "binary", "markers"])
def test_block_templates_require_regular_utf8_without_markers(box, source):
    path = box / "rules.txt"
    path.unlink()
    if source == "directory":
        path.mkdir()
    elif source == "link":
        (box / "target.txt").write_text("rules/\n")
        path.symlink_to("target.txt")
    else:
        path.write_bytes(b"\xff" if source == "binary" else b"# <kitflow>\n")
    with pytest.raises(KitFlowError):
        Catalog(box)


def test_conditional_fragments_stay_inside_the_managed_block(box, tmp_path):
    manifest = box / "kitflow-box.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'template="rules.txt"',
            'fragments=[{template="rules.txt"},{template="extra.txt",when=["extra"]}]',
        )
        + '\n[[components]]\nid="extra"\nlabel="Extra"\ncategory="Tools"\n'
    )
    (box / "extra.txt").write_text("# Extra\nextra/\n")
    project = tmp_path / "project"
    project.mkdir()
    apply(update(project, box, ["language", "extra"]), {})
    path = project / ".gitignore"
    owned = file_blocks.span(path.read_bytes())
    assert owned is not None
    assert owned[2] == b"# General\n*.tmp\n\n# Extra\nextra/\n"
    assert path.read_bytes().endswith(file_blocks.USER)
    apply(update(project, box), {})
    assert b"extra/" not in path.read_bytes()
    assert path.read_bytes().endswith(file_blocks.USER)


def test_deleted_user_markers_are_not_recreated(box, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    apply(update(project, box), {})
    path = project / ".gitignore"
    current = path.read_bytes().replace(b"# <user>\n", b"").replace(b"# </user>\n", b"")
    path.write_bytes(current)
    (box / "rules.txt").write_text("new/\n")
    apply(update(project, box), {})
    assert path.read_bytes() == current.replace(b"# General\n*.tmp\n", b"new/\n")


def test_cli_update_replaces_owned_edits_without_interactive_conflicts(box, tmp_path):
    import subprocess
    import sys

    project = tmp_path / "project"
    project.mkdir()
    command = [sys.executable, "-m", "kitflow", "-b", str(box), "-p", str(project)]
    first = subprocess.run(
        [*command, "init", "-c", "language", "-y"], capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    path = project / ".gitignore"
    path.write_bytes(path.read_bytes().replace(b"*.tmp", b"owned-edit/") + b"personal/\n")
    (box / "rules.txt").write_text("new/\n")
    result = subprocess.run([*command, "update", "-y"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Conflict" not in result.stdout
    assert "owned-edit/" not in result.stdout
    assert b"owned-edit/" not in path.read_bytes()
    assert path.read_bytes().endswith(file_blocks.USER + b"personal/\n")
