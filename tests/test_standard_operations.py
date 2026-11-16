"""Generic task contracts, independent of named project stacks."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from kitflow.catalog import Catalog

BOX = Path(__file__).parents[1] / "box"


@pytest.mark.parametrize("server", ["granian", "gunicorn", "uvicorn"])
def test_server_modes_use_the_selected_runtime_and_directory(tmp_path, server):
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls.json"
    uv = binary / "uv"
    uv.write_text(
        f'#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["CALL_LOG"]).write_text(json.dumps([os.getcwd(),sys.argv[1:]]))\n'
    )
    uv.chmod(0o755)
    project = tmp_path / "python directory"
    project.mkdir()
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "PROJECT_PYTHON_DIRECTORY": str(project),
        "PYTHON_APP": "sample:app",
        "SERVER_PORT": "9001",
        "BUILD_BEFORE_RUN": "false",
    }
    artifacts = Catalog(BOX).render([server])
    for mode in ("dev", "run"):
        content = artifacts[f"task.{mode}"].content
        assert isinstance(content, bytes)
        script = tomllib.loads(content.decode())["tasks"][mode]["run"]
        result = subprocess.run(["/bin/sh", "-c", script], env=env)
        assert result.returncode == 0
        directory, arguments = json.loads(log.read_text())
        assert Path(directory) == project.resolve()
        assert arguments[:2] == ["run", server]
        assert "sample:app" in arguments
        assert ("--reload" in arguments) == (mode == "dev")
        assert "9001" in " ".join(arguments)


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="SQLite CLI not installed")
@pytest.mark.parametrize("target", ["native", "docker"])
def test_sqlite_backup_restore_preserves_data_and_refuses_overwrites(tmp_path, target):
    database = tmp_path / "data.sqlite3"
    backup = tmp_path / "backup.sql"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE item(value TEXT)")
        connection.execute("INSERT INTO item VALUES ('original')")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text(
        f'#!{sys.executable}\nimport subprocess,sys\na=sys.argv; i=a.index("exec"); raise SystemExit(subprocess.call(a[i+3:]))\n'
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "DATABASE_SQLITE_PATH": str(database),
        "DATABASE_DOCKER_SQLITE_PATH": str(database),
        "usage_file": str(backup),
        "DATABASE_TARGET": target,
        "COMPOSE_FILE": "compose.yml",
        "COMPOSE_ENV_FILE": ".env",
        "DATABASE_DOCKER_SERVICE": "database",
    }

    def run(name, expected=0):
        result = subprocess.run(
            ["/bin/sh", "-eu", str(BOX / "tasks" / name)], env=env, capture_output=True, text=True
        )
        assert result.returncode == expected, result.stdout + result.stderr

    run("sqlite-backup.sh")
    content = backup.read_bytes()
    run("sqlite-backup.sh", 2)
    assert backup.read_bytes() == content
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE item SET value='changed'")
    run("sqlite-restore.sh")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM item").fetchone() == ("original",)
    backup.write_text("invalid SQL;")
    before = database.read_bytes()
    run("sqlite-restore.sh", 1)
    assert database.read_bytes() == before
    assert not list(tmp_path.glob(".kitflow-restore.*"))
    backup.write_bytes(content)
    Path(str(database) + "-wal").touch()
    run("sqlite-restore.sh", 2)
    assert database.read_bytes() == before


def test_xcode_backend_preserves_workspace_and_scheme_arguments(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls.json"
    tool = binary / "xcodebuild"
    tool.write_text(
        f'#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["CALL_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
    )
    tool.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "SWIFT_BACKEND": "xcode",
        "XCODE_PROJECT": "Project With Spaces.xcworkspace",
        "XCODE_SCHEME": "App Scheme",
        "XCODE_DESTINATION": "platform=macOS",
        "usage_action": "test",
        "usage_configuration": "Debug",
    }
    result = subprocess.run(["/bin/sh", "-eu", str(BOX / "tasks/_swift.sh")], env=env)
    assert result.returncode == 0
    arguments = json.loads(log.read_text())
    assert arguments[arguments.index("-workspace") + 1] == "Project With Spaces.xcworkspace"
    assert arguments[arguments.index("-scheme") + 1] == "App Scheme"
    assert arguments[-1] == "test"


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise executable not installed")
def test_generated_environment_uses_dotenv_before_fallbacks(tmp_path):
    from kitflow.engine import apply, load_config, plan

    project = tmp_path / "project"
    project.mkdir()
    apply(plan(project, Catalog(BOX), ["granian", "babel-i18n", "rust"], load_config(project)), {})
    (project / ".env").write_text(
        'SERVER_PORT=9876\nPYTHON_APP=sample:app\nI18N_LANGUAGES="fr uk"\nPROJECT_RUST_DIRECTORY="rust directory"\n'
    )
    result = subprocess.run(
        ["mise", "env", "--json"],
        cwd=project,
        env={
            **os.environ,
            "MISE_TRUSTED_CONFIG_PATHS": str(tmp_path),
            "MISE_CACHE_DIR": str(tmp_path / "cache"),
            "MISE_STATE_DIR": str(tmp_path / "state"),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    environment = json.loads(result.stdout)
    assert environment["SERVER_PORT"] == "9876"
    assert environment["PYTHON_APP"] == "sample:app"
    assert environment["I18N_LANGUAGES"] == "fr uk"
    assert environment["PROJECT_RUST_DIRECTORY"] == "rust directory"


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise executable not installed")
def test_mixed_build_runs_every_component_in_its_own_directory(tmp_path):
    from kitflow.engine import apply, load_config, plan

    project = tmp_path / "project"
    project.mkdir()
    (project / "mise.toml").write_text(
        '[vars]\nrust_directory="rust part"\njavascript_directory="frontend"\nswift_directory="swift part"\n'
    )
    for name in ("rust part", "frontend", "swift part"):
        (project / name).mkdir()
    apply(plan(project, Catalog(BOX), ["rust", "bun", "swift"], load_config(project)), {})
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands.jsonl"
    for name in ("cargo", "bun", "swift"):
        binary = binaries / name
        binary.write_text(
            f'#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nwith Path(os.environ["CALL_LOG"]).open("a") as stream:stream.write(json.dumps([Path(sys.argv[0]).name,os.getcwd()])+"\\n")\n'
        )
        binary.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "MISE_TRUSTED_CONFIG_PATHS": str(tmp_path),
        "MISE_CACHE_DIR": str(tmp_path / "cache"),
        "MISE_STATE_DIR": str(tmp_path / "state"),
    }
    result = subprocess.run(
        ["mise", "run", "--quiet", "build"], cwd=project, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = dict(json.loads(line) for line in log.read_text().splitlines())
    assert set(calls) == {"cargo", "bun", "swift"}
    assert Path(calls["cargo"]) == (project / "rust part").resolve()
    assert Path(calls["bun"]) == (project / "frontend").resolve()
    assert Path(calls["swift"]) == (project / "swift part").resolve()
