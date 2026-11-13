import subprocess
import sys
import tomllib
from pathlib import Path

from kitflow import cli, settings

CATALOG = Path(__file__).parent / "fixtures/catalog"


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
        "Apply local templates",
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
