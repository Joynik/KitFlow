import subprocess
import sys
import tomllib
from pathlib import Path

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
            "--catalog",
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
