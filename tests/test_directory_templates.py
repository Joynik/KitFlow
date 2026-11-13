import pytest

from kitflow.catalog import Catalog, KitFlowError
from kitflow.check import configuration_issues
from kitflow.engine import apply, load_config, plan


@pytest.fixture
def tree(tmp_path):
    box = tmp_path / "box"
    source = box / "templates" / ".vscode"
    source.mkdir(parents=True)
    (source / "settings.json").write_text("{}")
    (source / ".nested").mkdir()
    (source / ".nested" / ".hidden").write_bytes(b"\x00binary")
    (source / "empty").mkdir()
    (box / "kitflow-box.toml").write_text("""schema = 1
[[components]]
id = "editor"
label = "Editor"
category = "Tools"
[[files]]
id = "editor"
path = ".vscode"
template = "templates/.vscode"
when = ["editor"]
""")
    project = tmp_path / "project"
    project.mkdir()
    return box, source, project


def project_plan(box, project, selected=None):
    return plan(
        project, Catalog(box), ["editor"] if selected is None else selected, load_config(project)
    )


def test_directory_lifecycle_preserves_hidden_and_personal_files(tree):
    box, source, project = tree
    apply(project_plan(box, project), {})
    assert (project / ".vscode/.nested/.hidden").read_bytes() == b"\x00binary"
    assert not (project / ".vscode/empty").exists()
    (project / ".vscode/personal").write_text("mine")
    (source / "settings.json").write_text('{"updated": true}')
    (source / ".new").write_text("new")
    (source / ".nested/.hidden").unlink()
    apply(project_plan(box, project), {})
    assert (project / ".vscode/settings.json").read_text() == '{"updated": true}'
    assert (project / ".vscode/.new").read_text() == "new"
    assert not (project / ".vscode/.nested/.hidden").exists()
    assert not configuration_issues(box, project)
    apply(project_plan(box, project, []), {})
    assert (project / ".vscode/personal").read_text() == "mine"
    assert not (project / ".vscode/.new").exists()


def test_modified_child_requires_resolution_and_keep_persists(tree):
    box, source, project = tree
    apply(project_plan(box, project), {})
    (project / ".vscode/settings.json").write_text('{"personal": true}')
    (source / "settings.json").write_text('{"standard": true}')
    result = project_plan(box, project)
    change = next(c for c in result.changes if c.artifact.path.endswith("settings.json"))
    assert change.conflict
    change.decision = "keep"
    apply(result, {})
    assert not project_plan(box, project).changes
    assert project_plan(box, project, []).changes
    apply(project_plan(box, project, []), {})
    assert (project / ".vscode/settings.json").read_text() == '{"personal": true}'


@pytest.mark.parametrize("directory", [False, True])
def test_absolute_symlinks_in_directory_are_rejected(tree, directory):
    box, source, _ = tree
    (source / ".link").symlink_to(
        source if directory else source / "settings.json", target_is_directory=directory
    )
    with pytest.raises(KitFlowError, match="Only relative symbolic links"):
        Catalog(box)


def test_check_reports_nested_template_and_project_syntax(tree):
    box, source, project = tree
    apply(project_plan(box, project), {})
    (source / "settings.json").write_text("{invalid")
    (project / ".vscode/settings.json").write_text("{broken")
    issues = configuration_issues(box, project)
    assert {path for path, _ in issues} >= {
        source / "settings.json",
        project / ".vscode/settings.json",
    }


def test_overlapping_targets_are_rejected(tree):
    box, _, _ = tree
    with (box / "kitflow-box.toml").open("a") as stream:
        stream.write("""
[[files]]
id = "duplicate"
path = ".vscode/.nested"
template = "templates/.vscode/settings.json"
""")
    with pytest.raises(KitFlowError, match="Duplicate or reserved"):
        Catalog(box)


def test_once_directory_keeps_existing_and_retired_files(tree):
    box, source, project = tree
    manifest = box / "kitflow-box.toml"
    manifest.write_text(manifest.read_text() + 'mode = "once"\n')
    apply(project_plan(box, project), {})
    (source / "settings.json").write_text('{"new": true}')
    assert not project_plan(box, project).changes
    apply(project_plan(box, project, []), {})
    assert (project / ".vscode/settings.json").read_text() == "{}"


def test_modified_removed_child_is_protected(tree):
    box, source, project = tree
    apply(project_plan(box, project), {})
    (project / ".vscode/settings.json").write_text("personal")
    (source / "settings.json").unlink()
    result = project_plan(box, project)
    assert any(c.conflict and c.artifact.path == ".vscode/settings.json" for c in result.changes)
    with pytest.raises(KitFlowError, match="Resolve conflicts"):
        apply(result, {})
    assert (project / ".vscode/settings.json").read_text() == "personal"


def test_target_symlink_is_rejected(tree, tmp_path):
    box, _, project = tree
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".vscode").symlink_to(outside, target_is_directory=True)
    with pytest.raises(KitFlowError, match="Symbolic links"):
        project_plan(box, project)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("target", ["settings.json", ".", "../missing-skill", ".nested"])
def test_relative_links_are_preserved_without_traversal(tree, target):
    import os

    box, source, project = tree
    (source / ".skill").symlink_to(target)
    artifacts = Catalog(box).render(["editor"])
    assert artifacts["editor/.skill"].content == target
    assert artifacts["editor/.skill"].kind == "symlink"
    assert not any(identity.startswith("editor/.skill/") for identity in artifacts)
    apply(project_plan(box, project), {})
    link = project / ".vscode/.skill"
    assert link.is_symlink()
    assert os.readlink(link) == target
    assert not project_plan(box, project).changes
    assert not configuration_issues(box, project)
    apply(project_plan(box, project, []), {})
    assert not link.is_symlink()
    assert (source / "settings.json").read_text() == "{}"


def test_link_target_contents_are_never_checked_or_copied(tree):
    box, source, project = tree
    external = source.parent / "external.json"
    external.write_text("{not json")
    (source / "linked.json").symlink_to("../external.json")
    (project / "external.json").write_text("{also invalid")
    apply(project_plan(box, project), {})
    assert (project / ".vscode/linked.json").is_symlink()
    assert not configuration_issues(box, project)
    assert external.read_text() == "{not json"
    assert (project / "external.json").read_text() == "{also invalid"


def test_link_lifecycle_conflict_and_snapshot_protection(tree):
    import os

    box, source, project = tree
    link = source / ".skill"
    link.symlink_to("first")
    apply(project_plan(box, project), {})
    link.unlink()
    link.symlink_to("second")
    result = project_plan(box, project)
    apply(result, {})
    output = project / ".vscode/.skill"
    assert os.readlink(output) == "second"
    link.unlink()
    link.symlink_to("third")
    result = project_plan(box, project)
    output.unlink()
    output.symlink_to("personal")
    with pytest.raises(KitFlowError, match="changed after planning"):
        apply(result, {})
    result = project_plan(box, project)
    assert result.changes[0].conflict
    result.changes[0].decision = "keep"
    apply(result, {})
    apply(project_plan(box, project, []), {})
    assert os.readlink(output) == "personal"


def test_single_link_template_and_file_link_transitions(tree):
    import os

    box, source, project = tree
    link = source / "settings.json"
    link.unlink()
    link.symlink_to("elsewhere")
    apply(project_plan(box, project), {})
    output = project / ".vscode/settings.json"
    assert os.readlink(output) == "elsewhere"
    link.unlink()
    link.write_text("{}")
    apply(project_plan(box, project), {})
    assert not output.is_symlink()
    assert output.read_text() == "{}"
    manifest = box / "kitflow-box.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('templates/.vscode"', 'templates/.vscode/settings.json"')
        .replace('path = ".vscode"', 'path = "single.json"')
    )
    link.unlink()
    link.symlink_to("missing")
    artifacts = Catalog(box).render(["editor"])
    assert artifacts["editor"].content == "missing"
    assert artifacts["editor"].path == "single.json"


def test_link_write_failure_rolls_back_original_entry(tree, monkeypatch):
    import os

    from kitflow import engine

    box, source, project = tree
    (source / ".skill").symlink_to("original")
    apply(project_plan(box, project), {})
    (source / ".skill").unlink()
    (source / ".skill").symlink_to("updated")
    original_write = engine.atomic_write

    failed = False

    def fail_config(path, content, mode=None):
        nonlocal failed
        if path.name == "kitflow.toml" and not failed:
            failed = True
            raise OSError("injected failure")
        original_write(path, content, mode)

    monkeypatch.setattr(engine, "atomic_write", fail_config)
    with pytest.raises(OSError, match="injected failure"):
        apply(project_plan(box, project), {})
    assert os.readlink(project / ".vscode/.skill") == "original"


def test_diff_shows_literal_link_target(tree, capsys):
    from kitflow.cli import show_diff

    box, source, project = tree
    (source / ".skill").symlink_to("../skills/example")
    result = project_plan(box, project)
    change = next(c for c in result.changes if c.artifact.kind == "symlink")
    show_diff(change)
    assert "symlink -> ../skills/example" in capsys.readouterr().out


def test_user_replacing_link_with_file_requires_confirmation(tree):
    box, source, project = tree
    (source / ".skill").symlink_to("original")
    apply(project_plan(box, project), {})
    output = project / ".vscode/.skill"
    output.unlink()
    output.write_bytes(b"symlink\0original")
    result = project_plan(box, project)
    assert result.changes[0].conflict
    with pytest.raises(KitFlowError, match="Resolve conflicts"):
        apply(result, {})
    assert output.read_bytes() == b"symlink\0original"
