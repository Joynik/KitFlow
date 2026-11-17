from pathlib import Path

import pytest
import tomlkit

from kitflow.catalog import Catalog, KitFlowError
from kitflow.engine import apply, load_config, plan, preview_files
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
    app = ResetFiles({"PROJECT.md": (b"personal\n", b""), "binary.pdf": (b"\xff", b"\x00")})
    async with app.run_test() as pilot:
        choices = app.query_one("#files", Components)
        assert choices.selected == []
        assert not app.query_one("#diff").display
        await pilot.press("right")
        assert app.query_one("#diff").display
        assert choices.selected == []
        await pilot.press("left", "down", "right")
        assert choices.selected == []
        await pilot.press("enter")
        assert choices.selected == ["binary.pdf"]
        await pilot.click("#replace")
    assert app.return_value == ["binary.pdf"]


def test_reset_cli_requires_file_selection_and_preserves_unselected_files(tmp_path, monkeypatch):
    from kitflow import cli

    catalog = configured(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(ResetFiles, "run", lambda self: ["PROJECT.md"])
    args = cli.parser().parse_args(
        ["update", "--reset", "--box", str(catalog.root), "--project", str(tmp_path)]
    )
    before = (tmp_path / "mise.toml").read_bytes()
    assert cli.run(args) == 0
    assert (tmp_path / "PROJECT.md").read_bytes() == b""
    assert (tmp_path / "mise.toml").read_bytes() == before
    saved = (tmp_path / "kitflow.toml").read_bytes()
    monkeypatch.setattr(ResetFiles, "run", lambda self: None)
    assert cli.run(args) == 0
    assert (tmp_path / "kitflow.toml").read_bytes() == saved
    args.yes = True
    with pytest.raises(KitFlowError, match="interactively"):
        cli.run(args)


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
