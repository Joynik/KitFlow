from pathlib import Path

import pytest
import tomlkit

from kitflow.catalog import Catalog, KitFlowError
from kitflow.engine import apply, load_config, plan, preview_files
from kitflow.reset import Edit, ResetFile, reset_files, select_reset
from kitflow.tui import Components, ResetFiles


def configured(tmp_path):
    catalog = Catalog(Path(__file__).parents[1] / "box")
    apply(plan(tmp_path, catalog, ["python", "pytest", "agents"], load_config(tmp_path)), {})
    (tmp_path / "PROJECT.md").write_text("Personal project notes\n")
    path = tmp_path / "mise.toml"
    text = path.read_text().replace('project_root = "."', 'project_root = "backend"')
    text = text.replace("[vars]\n", '[vars]\npersonal = "keep"\n')
    path.write_text(text + '\n[tasks.personal]\nrun = "echo personal"\n')
    return catalog


def test_reset_only_selected_file_and_preserves_user_mise_entries(tmp_path):
    catalog = configured(tmp_path)
    result = plan(
        tmp_path, catalog, ["python", "pytest", "agents"], load_config(tmp_path), reset=True
    )
    candidates = preview_files(result)
    assert candidates["PROJECT.md"] == (b"Personal project notes\n", b"")
    mise_preview = candidates["mise.toml"][1]
    assert isinstance(mise_preview, bytes)
    assert b'project_root = "."' in mise_preview
    for change in result.changes:
        if change.artifact.path != "mise.toml" or change.operation == "detach":
            change.decision = "skip"
    apply(result, {})
    assert (tmp_path / "mise.toml").read_bytes() == candidates["mise.toml"][1]
    document = tomlkit.parse((tmp_path / "mise.toml").read_text())
    assert document["vars"]["personal"] == "keep"
    assert document["tasks"]["personal"]["run"] == "echo personal"
    assert (tmp_path / "PROJECT.md").read_text() == "Personal project notes\n"


def test_reset_creation_only_file_and_concurrent_change_protection(tmp_path):
    catalog = configured(tmp_path)
    result = plan(
        tmp_path, catalog, ["python", "pytest", "agents"], load_config(tmp_path), reset=True
    )
    for change in result.changes:
        if change.artifact.path != "PROJECT.md":
            change.decision = "skip"
    (tmp_path / "PROJECT.md").write_text("Changed while reviewing\n")
    with pytest.raises(KitFlowError, match="changed after planning"):
        apply(result, {})
    assert (tmp_path / "PROJECT.md").read_text() == "Changed while reviewing\n"
    result = plan(
        tmp_path, catalog, ["python", "pytest", "agents"], load_config(tmp_path), reset=True
    )
    for change in result.changes:
        if change.artifact.path != "PROJECT.md":
            change.decision = "skip"
    apply(result, {})
    assert (tmp_path / "PROJECT.md").read_bytes() == b""


@pytest.mark.asyncio
async def test_reset_file_picker_starts_unchecked_and_diff_does_not_select():
    app = ResetFiles(
        {
            "PROJECT.md": ResetFile(
                [],
                [
                    Edit("Replace lines 1–2", "personal", "new"),
                    Edit("Replace line 10", "old", "new"),
                ],
            ),
            "binary.pdf": ResetFile([], [Edit("Replace file", "Binary file", "Binary file")]),
        }
    )
    async with app.run_test(size=(100, 28)) as pilot:
        choices = app.query_one("#files", Components)
        assert choices.selected == []
        assert not app.query_one("#diff").display
        await pilot.press("enter")
        assert app.query_one("#diff").display
        assert not app.query_one("#panes").has_class("stacked")
        await pilot.resize_terminal(70, 28)
        assert app.query_one("#panes").has_class("stacked")
        assert choices.selected == []
        await pilot.press("down", "space", "left")
        assert choices.selected == []
        assert app.selected == {"PROJECT.md": {1}}
        await pilot.press("down", "space")
        assert choices.selected == ["binary.pdf"]
        await pilot.click("#replace")
    assert app.return_value == {"PROJECT.md": {1}, "binary.pdf": {0}}


def test_reset_cli_requires_file_selection_and_preserves_unselected_files(tmp_path, monkeypatch):
    from kitflow import cli

    catalog = configured(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(ResetFiles, "run", lambda self: {"PROJECT.md": {0}})

    def choose(_title, options, _default):
        assert ("review", "Review and update files") in options
        return "review"

    monkeypatch.setattr(cli, "choose_action", choose)
    args = cli.parser().parse_args(
        ["update", "--box", str(catalog.root), "--project", str(tmp_path)]
    )
    before = (tmp_path / "mise.toml").read_bytes()
    assert cli.run(args) == 0
    assert (tmp_path / "PROJECT.md").read_bytes() == b""
    assert (tmp_path / "mise.toml").read_bytes() == before
    saved = (tmp_path / "kitflow.toml").read_bytes()
    monkeypatch.setattr(ResetFiles, "run", lambda self: None)
    assert cli.run(args) == 0
    assert (tmp_path / "kitflow.toml").read_bytes() == saved
    with pytest.raises(SystemExit) as error:
        cli.parser().parse_args(["update", "--reset"])
    assert error.value.code == 2


def test_reset_preserves_detached_user_task(tmp_path):
    catalog = configured(tmp_path)
    path = tmp_path / "mise.toml"
    text = (
        path.read_text()
        .replace("# kitflow:begin task.help\n", "")
        .replace("# kitflow:end task.help\n", "")
    )
    path.write_text(text)
    result = plan(
        tmp_path, catalog, ["python", "pytest", "agents"], load_config(tmp_path), reset=True
    )
    preview = preview_files(result)["mise.toml"][1]
    assert isinstance(preview, bytes)
    assert b"# kitflow:begin task.help" not in preview
    assert tomlkit.parse(preview.decode())["tasks"]["help"] == tomlkit.parse(text)["tasks"]["help"]


def test_reset_applies_one_mise_setting_without_resetting_task(tmp_path):
    catalog = configured(tmp_path)
    path = tmp_path / "mise.toml"
    text = path.read_text().replace("mise tasks ls", "echo local")
    assert text != path.read_text()
    text = text.replace("task.quiet = true", "task.quiet = false")
    path.write_text(text)
    document = load_config(tmp_path)
    result = plan(tmp_path, catalog, document["selection"]["components"], document, reset=True)
    files = reset_files(result)
    edits = files["mise.toml"].edits
    assert any("task.help" in edit.label for edit in edits)
    quiet = next(i for i, edit in enumerate(edits) if "settings.task.quiet" in edit.label)
    select_reset(result, files, {"mise.toml": {quiet}})
    apply(result, {})
    updated = path.read_text()
    assert "task.quiet = true" in updated
    assert 'project_root = "backend"' in updated
    assert "echo local" in updated


def text_project(tmp_path, template):
    box = tmp_path / "box"
    box.mkdir()
    (box / "kitflow-box.toml").write_text(
        'schema = 4\n[[components]]\nid = "example"\nlabel = "Example"\ncategory = "Tools"\n'
        '[[files]]\nid = "example"\npath = "example.toml"\ntemplate = "template.toml"\n'
    )
    (box / "template.toml").write_text(template)
    project = tmp_path / "project"
    project.mkdir()
    path = project / "example.toml"
    catalog = Catalog(box)
    apply(plan(project, catalog, ["example"], load_config(project)), {})
    return catalog, project, path


def test_partial_file_reset_preserves_unselected_managed_lines(tmp_path):
    template = "first = 1\n" + "\n".join(f"key{i} = 0" for i in range(8)) + "\nlast = 1\n"
    catalog, project, path = text_project(tmp_path, template)
    path.write_text(template.replace("first = 1", "first = 2").replace("last = 1", "last = 3"))
    result = plan(project, catalog, ["example"], load_config(project), reset=True)
    files = reset_files(result)
    assert len(files["example.toml"].edits) == 2
    select_reset(result, files, {"example.toml": {0}})
    apply(result, {})
    assert path.read_text() == template.replace("last = 1", "last = 3")
    assert plan(project, catalog, ["example"], load_config(project)).changes[0].conflict
    again = plan(project, catalog, ["example"], load_config(project), reset=True)
    assert len(reset_files(again)["example.toml"].edits) == 1


def test_invalid_toml_from_partial_reset_is_rejected_before_writing(tmp_path):
    gap = "\n" + "\n".join(f"key{i} = 0" for i in range(8)) + "\n"
    catalog, project, path = text_project(tmp_path, "first = 1" + gap + "last = 0\n")
    local = "last = 1" + gap + "first = 0\n"
    path.write_text(local)
    result = plan(project, catalog, ["example"], load_config(project), reset=True)
    files = reset_files(result)
    assert len(files["example.toml"].edits) == 2
    state = (project / "kitflow.toml").read_bytes()
    with pytest.raises(KitFlowError, match="invalid TOML in example.toml"):
        select_reset(result, files, {"example.toml": {0}})
    assert path.read_text() == local
    assert (project / "kitflow.toml").read_bytes() == state
