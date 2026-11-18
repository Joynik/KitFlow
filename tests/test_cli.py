import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from kitflow import cli, settings
from kitflow.catalog import KitFlowError

CATALOG = Path(__file__).parent / "fixtures/catalog"


@pytest.mark.parametrize("flag", ["-v", "--version"])
def test_cli_reports_package_version(flag, capsys):
    metadata = Path(__file__).resolve().parents[1] / "pyproject.toml"
    version = tomllib.loads(metadata.read_text())["project"]["version"]
    with pytest.raises(SystemExit) as exit_info:
        cli.parser().parse_args([flag])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"KitFlow {version}\n"


def test_update_rejects_config_edit_after_loading_selection(tmp_path, monkeypatch):
    init = ["init", "-b", str(CATALOG), "-p", str(tmp_path), "-c", "python", "-y"]
    assert cli.run(cli.parser().parse_args(init)) == 0
    path = tmp_path / "kitflow.toml"
    updated = path.read_text().replace('"python"', '"agents"', 1)
    assert updated != path.read_text()
    load_box = cli.load_box

    def edit_then_load(box):
        path.write_text(updated)
        return load_box(box)

    monkeypatch.setattr(cli, "load_box", edit_then_load)
    args = cli.parser().parse_args(["update", "-b", str(CATALOG), "-p", str(tmp_path), "-y"])
    with pytest.raises(KitFlowError, match="kitflow.toml changed after planning"):
        cli.run(args)
    assert path.read_text() == updated


def invoke(project, *arguments):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "kitflow",
            *arguments,
            "--project",
            str(project),
            "--box",
            str(CATALOG),
        ],
        capture_output=True,
        text=True,
    )


def test_real_cli_lifecycle(tmp_path):
    result = invoke(tmp_path, "init", "--components", "django,ruff,agents", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    data = tomllib.loads((tmp_path / "mise.toml").read_text())
    assert "manage.py check" in data["tasks"]["lint"]["run"]
    assert "ruff check" in data["tasks"]["lint"]["run"]
    assert "tools" not in data
    assert (tmp_path / "PROJECT.md").read_bytes() == b""
    assert invoke(tmp_path, "status").returncode == 0
    (tmp_path / "ruff.toml").write_text("# User settings\n")
    assert invoke(tmp_path, "status").returncode == 1
    difference = invoke(tmp_path, "diff")
    assert difference.returncode == 1
    assert difference.stderr == ""
    assert "current/ruff.toml" in difference.stdout
    assert invoke(tmp_path, "update", "--yes").returncode == 2
    assert (tmp_path / "ruff.toml").read_text() == "# User settings\n"
    result = invoke(tmp_path, "init", "--components", "python,agents", "--yes")
    assert result.returncode == 2
    (tmp_path / "ruff.toml").write_bytes((CATALOG / "templates/ruff.toml").read_bytes())
    assert invoke(tmp_path, "init", "--components", "python,agents", "--yes").returncode == 0
    assert not (tmp_path / "ruff.toml").exists()
    assert "tasks" not in tomllib.loads((tmp_path / "mise.toml").read_text())


def test_init_needs_explicit_noninteractive_selection(tmp_path):
    result = invoke(tmp_path, "init", "--yes")
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


def test_short_options_configure_another_project_and_restore_management(tmp_path):
    command = [sys.executable, "-m", "kitflow"]
    options = ["-p", str(tmp_path), "-b", str(CATALOG), "-y"]
    result = subprocess.run(
        [*command, "init", "-c", "ruff", *options], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "ruff.toml").exists()
    assert not settings.box_path().exists()
    config = tmp_path / "kitflow.toml"
    config.write_text(config.read_text().replace("excluded = []", 'excluded = ["ruff"]'))
    result = subprocess.run(
        [*command, "init", "-m", "ruff", *options], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert tomllib.loads(config.read_text())["selection"]["excluded"] == []


def test_instruction_is_available_offline_without_creating_the_box():
    result = subprocess.run([sys.executable, "-m", "kitflow", "-i"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Using KitFlow" in result.stdout
    assert not settings.box_path().exists()


def test_instruction_prefers_the_selected_local_box(tmp_path):
    (tmp_path / "INSTRUCTION.md").write_text("# My custom guide\n")
    result = subprocess.run(
        [sys.executable, "-m", "kitflow", "--instruction", "-b", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "My custom guide" in result.stdout
    assert not settings.box_path().exists()


def test_help_describes_commands_and_box_options():
    help_text = cli.parser().format_help()
    for description in [
        "Choose or change project components",
        "Update project files",
        "List pending changes",
        "Show proposed file differences",
        "Show the local box location",
    ]:
        assert description in help_text
    assert "--box" in help_text
    assert "--catalog" not in help_text


def test_config_does_not_prepare_the_box(capsys):
    assert cli.run(cli.parser().parse_args(["config"])) == 0
    assert str(settings.box_path()) in capsys.readouterr().out.replace("\n", "")
    assert not settings.box_path().exists()


def test_bundled_guide_matches_published_instructions():
    from kitflow.source import read_instructions

    assert read_instructions() == (Path(__file__).parents[1] / "docs/INSTRUCTION.md").read_text()


def test_update_can_reconfigure_and_remove_components(tmp_path, monkeypatch):
    from kitflow.tui import Configurator, Selection

    assert (
        cli.run(
            cli.parser().parse_args(
                ["init", "-c", "ruff,agents", "-b", str(CATALOG), "-p", str(tmp_path), "-y"]
            )
        )
        == 0
    )
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    answers = iter(["setup", "apply"])
    monkeypatch.setattr(cli, "choose_action", lambda *_args, **_kwargs: next(answers))
    starts = []

    def configure(self):
        starts.append(self.model.chosen.copy())
        assert self.model.seen
        return Selection(["python", "agents"], [])

    monkeypatch.setattr(Configurator, "run", configure)
    assert (
        cli.run(cli.parser().parse_args(["update", "-b", str(CATALOG), "-p", str(tmp_path)])) == 0
    )
    assert starts == [{"python", "ruff", "agents"}]
    assert not (tmp_path / "ruff.toml").exists()
    assert tomllib.loads((tmp_path / "kitflow.toml").read_text())["selection"]["components"] == [
        "python",
        "agents",
    ]


def test_update_yes_skips_menu_and_wizard(tmp_path, monkeypatch):
    from kitflow.tui import Configurator

    assert invoke(tmp_path, "init", "-c", "ruff", "-y").returncode == 0
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Unexpected interactive setup")

    monkeypatch.setattr(cli, "choose_action", unexpected)
    monkeypatch.setattr(Configurator, "run", unexpected)
    assert (
        cli.run(cli.parser().parse_args(["update", "-y", "-b", str(CATALOG), "-p", str(tmp_path)]))
        == 0
    )


def test_update_wizard_cancel_does_not_write_files(tmp_path, monkeypatch):
    from kitflow.tui import Configurator

    assert invoke(tmp_path, "init", "-c", "ruff", "-y").returncode == 0
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "choose_action", lambda *_args, **_kwargs: "setup")
    monkeypatch.setattr(Configurator, "run", lambda self: None)
    assert (
        cli.run(cli.parser().parse_args(["update", "-b", str(CATALOG), "-p", str(tmp_path)])) == 0
    )
    assert {p: p.read_bytes() for p in before} == before


def test_removed_profile_option_is_rejected(tmp_path):
    assert invoke(tmp_path, "init", "--profile", "example", "-y").returncode == 2
    assert not list(tmp_path.iterdir())


def test_update_without_changes_shows_message_without_table_or_confirmation(
    tmp_path, monkeypatch, capsys
):
    assert invoke(tmp_path, "init", "-c", "ruff", "-y").returncode == 0
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    calls = []

    def choose(*args):
        calls.append(args)
        return "files"

    monkeypatch.setattr(cli, "choose_action", choose)
    assert (
        cli.run(cli.parser().parse_args(["update", "-b", str(CATALOG), "-p", str(tmp_path)])) == 0
    )
    output = capsys.readouterr().out
    assert "No files need updating." in output
    assert "uses schema 1" in " ".join(output.split())
    assert "Review plan" not in output
    assert "Configuration saved" not in output
    assert len(calls) == 1


def test_schema_warning_preserves_older_catalog_and_is_quiet_for_current_schema(tmp_path, capsys):
    manifest = tmp_path / "kitflow-box.toml"
    for schema in (1, 2, 3, 4):
        original = f"# Personal catalog\nschema = {schema}\n"
        manifest.write_text(original)
        cli.warn_box_schema(tmp_path)
        output = capsys.readouterr().out
        if schema < 4:
            assert f"uses schema {schema}" in output
            assert "uses schema 4" in output
            assert "manually" in output
        else:
            assert not output
        assert manifest.read_text() == original
