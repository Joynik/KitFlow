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
from kitflow.wizard import Wizard

BOX = Path(__file__).parents[1] / "box"


def test_vsix_packaging_requires_bundle(tmp_path):
    catalog = Catalog(BOX)
    selected = ["javascript", "vscode-extension"]
    packaging = "vscode-extension-vsix"
    assert not Wizard(catalog, selected, []).eligible(packaging)
    artifact = catalog.render([*selected, packaging])["task.package"]
    assert isinstance(artifact.content, bytes)
    script = tomllib.loads(artifact.content.decode())["tasks"]["package"]["run"]
    result = subprocess.run(["/bin/sh", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "Select Bun build or esbuild" in result.stderr
    assert not list(tmp_path.glob("*.vsix"))
    for bundler in ("vscode-extension-bun", "vscode-extension-esbuild"):
        components = [*selected, bundler]
        resolved = catalog.resolve(components)
        assert Wizard(catalog, resolved, []).eligible(packaging)
        artifact = catalog.render([*resolved, packaging])["task.package"]
        assert isinstance(artifact.content, bytes)
        script = tomllib.loads(artifact.content.decode())["tasks"]["package"]["run"]
        assert "mise run extension:prepare && npm exec --no -- vsce package" in script


@pytest.mark.parametrize(
    ("framework", "servers"),
    [
        ("django", {"granian", "gunicorn", "uvicorn", "gunicorn-uvicorn"}),
        ("fastapi", {"granian", "uvicorn"}),
        ("flask", {"granian", "gunicorn"}),
    ],
)
def test_python_server_choices_follow_the_framework(framework, servers):
    wizard = Wizard(Catalog(BOX), [framework], [])
    step = next(step for step in wizard.steps() if "Python servers" in step.categories)
    assert set(wizard.choices(step)) == servers


@pytest.mark.parametrize("server", ["granian", "gunicorn", "uvicorn", "gunicorn-uvicorn"])
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
    (project / "media files").mkdir()
    (project / "cache").mkdir()
    patterns = [r"\.tmp$", r"\.bak$"] if server == "granian" else ["*.tmp", "*.bak"]
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "PYTHON_SOURCE": str(project),
        "PYTHON_APP": "sample:app",
        "SERVER_PORT": "9001",
        "SERVER_RELOAD_IGNORE_DIRS": "media files\ncache",
        "SERVER_RELOAD_IGNORE_PATTERNS": "\n".join(patterns),
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
        runtime = (
            {"dev": "uvicorn", "run": "gunicorn"}[mode] if server == "gunicorn-uvicorn" else server
        )
        assert arguments[:2] == ["run", runtime]
        assert "sample:app" in arguments
        assert ("--reload" in arguments) == (mode == "dev")
        assert "9001" in " ".join(arguments)
        if mode == "dev" and runtime == "granian":
            assert arguments[-4:] == [
                "--reload-ignore-dirs=media files",
                "--reload-ignore-dirs=cache",
                *[f"--reload-ignore-patterns={pattern}" for pattern in patterns],
            ]
        elif mode == "dev" and runtime == "uvicorn":
            assert arguments[-4:] == [
                f"--reload-exclude={project.resolve() / 'media files'}",
                f"--reload-exclude={project.resolve() / 'cache'}",
                *[f"--reload-exclude={pattern}" for pattern in patterns],
            ]
        else:
            assert not any(arg.startswith("--reload-") for arg in arguments)
        if server == "gunicorn-uvicorn" and mode == "run":
            assert "uvicorn_worker.UvicornWorker" in arguments


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
        "SQLITE_DATABASE_PATH": str(database),
        "SQLITE_CONTAINER_PATH": str(database),
        "usage_file": str(backup),
        "DATABASE_EXECUTION_MODE": target,
        "COMPOSE_FILE": "compose.yml",
        "COMPOSE_ENV_FILE": ".env",
        "DATABASE_DOCKER_SERVICE": "database",
    }

    def run(name, expected=0):
        artifact = Catalog(BOX).render(["sqlite", "docker"])[f"task.db:{name}"]
        assert isinstance(artifact.content, bytes)
        script = tomllib.loads(artifact.content.decode())["tasks"][f"db:{name}"]["run"]
        result = subprocess.run(["/bin/sh", "-c", script], env=env, capture_output=True, text=True)
        assert result.returncode == expected, result.stdout + result.stderr

    run("backup")
    content = backup.read_bytes()
    run("backup", 2)
    assert backup.read_bytes() == content
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE item SET value='changed'")
    run("restore")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM item").fetchone() == ("original",)
    backup.write_text("invalid SQL;")
    before = database.read_bytes()
    run("restore", 1)
    assert database.read_bytes() == before
    assert not list(tmp_path.glob(".kitflow-restore.*"))
    backup.write_bytes(content)
    Path(str(database) + "-wal").touch()
    run("restore", 2)
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


def test_compose_wrapper_handles_project_and_database_tasks(tmp_path):
    wrapper = tmp_path / "docker wrapper.sh"
    wrapper.write_text('printf "%s\\n" "$@"\n')
    catalog = Catalog(BOX)
    artifacts = catalog.render(["docker", "sqlite"])
    database = tmp_path / "backup.sql"
    env = {
        **os.environ,
        "COMPOSE_WRAPPER": str(wrapper),
        "COMPOSE_FILE": "compose.yml",
        "COMPOSE_ENV_FILE": ".env",
        "DATABASE_DOCKER_SERVICE": "db",
        "DATABASE_EXECUTION_MODE": "docker",
        "SQLITE_MODE": "local",
        "SQLITE_DATABASE_PATH": str(tmp_path / "app.sqlite3"),
        "SQLITE_CONTAINER_PATH": "/data/application.sqlite3",
        "usage_file": str(database),
    }

    def run(task, **overrides):
        content = artifacts[f"task.{task}"].content
        assert isinstance(content, bytes)
        script = tomllib.loads(content.decode())["tasks"][task]["run"]
        return subprocess.run(
            ["/bin/sh", "-c", script], env={**env, **overrides}, capture_output=True, text=True
        )

    result = run("docker:up")
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["up", "--detach"]
    result = run("db:backup", SQLITE_MODE="remote")
    assert result.returncode == 2
    assert "requires a local SQLite file" in result.stderr
    assert not database.exists()
    result = run("db:backup")
    assert result.returncode == 0
    assert database.read_text().splitlines() == [
        "exec",
        "-T",
        "db",
        "sqlite3",
        "-readonly",
        "-bail",
        "/data/application.sqlite3",
        ".dump",
    ]


def test_database_guard_runs_before_tests_and_uses_django_test_settings(tmp_path):
    uv = tmp_path / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = --project ]; then exec "$TEST_PYTHON" -; fi\n'
        'printf "%s\\n" "$DJANGO_SETTINGS_MODULE"\n'
    )
    uv.chmod(0o755)
    artifact = Catalog(BOX).render(["django-tests", "test-postgresql"])["task.test"]
    assert isinstance(artifact.content, bytes)
    script = tomllib.loads(artifact.content.decode())["tasks"]["test"]["run"]
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "TEST_PYTHON": sys.executable,
        "TEST_DATABASE_BACKEND": "postgresql",
        "PGDATABASE": "application",
        "PGUSER": "app_user",
        "TEST_DATABASE_URL": "postgresql://tester:placeholder@localhost/application_test",
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_TEST_SETTINGS_MODULE": "config.test_settings",
        "PYTHON_SOURCE": str(tmp_path),
    }

    def run(**overrides):
        return subprocess.run(
            ["/bin/sh", "-c", script], env={**env, **overrides}, capture_output=True, text=True
        )

    assert run().stdout.strip() == "config.test_settings"
    for url in ("", "postgresql://tester:placeholder@localhost/application"):
        result = run(TEST_DATABASE_URL=url)
        assert result.returncode != 0
        assert not result.stdout
        assert "placeholder" not in result.stderr
    primary = str(tmp_path / "app.sqlite3")
    result = run(
        TEST_DATABASE_BACKEND="sqlite",
        TEST_SQLITE_DATABASE_PATH=primary,
        SQLITE_DATABASE_PATH=primary,
    )
    assert result.returncode != 0
    assert "points to the application database" in result.stderr


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise executable not installed")
def test_generated_environment_uses_dotenv_before_fallbacks(tmp_path):
    from kitflow.engine import apply, load_config, plan

    project = tmp_path / "project"
    project.mkdir()
    apply(
        plan(
            project,
            Catalog(BOX),
            ["granian", "babel-i18n", "rust", "docker", "test-sqlite", "pytest"],
            load_config(project),
        ),
        {},
    )
    (project / ".env").write_text(
        'SERVER_PORT=9876\nPYTHON_APP=sample:app\nI18N_LANGUAGES="fr uk"\nSERVER_RELOAD_IGNORE_DIRS="media\ncache"\nPROJECT_RUST_DIRECTORY="rust directory"\n'
        'DOCKER_SOURCE="deployment files"\nCOMPOSE_FILE="custom.yml"\nCOMPOSE_WRAPPER="deployment files/compose.sh"\n'
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
    assert environment["COMPOSE_FILE"] == str(project.resolve() / "deployment files/custom.yml")
    assert environment["COMPOSE_ENV_FILE"] == str(project.resolve() / ".env")
    assert environment["COMPOSE_WRAPPER"] == str(project.resolve() / "deployment files/compose.sh")
    assert environment["TEST_SQLITE_DATABASE_PATH"] == ":memory:"
    assert environment["SERVER_RELOAD_IGNORE_DIRS"] == "media\ncache"
    assert environment["SERVER_RELOAD_IGNORE_PATTERNS"] == ""
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


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise executable not installed")
@pytest.mark.parametrize("value", ["data with spaces/app.sqlite3", "/tmp/absolute app.sqlite3"])
def test_sqlite_path_override_is_resolved_from_project_root(tmp_path, value):
    from kitflow.engine import apply, load_config, plan

    apply(plan(tmp_path, Catalog(BOX), ["sqlite"], load_config(tmp_path)), {})
    (tmp_path / ".env").write_text(f'SQLITE_DATABASE_PATH="{value}"\n')
    result = subprocess.run(
        ["mise", "env", "--json"],
        cwd=tmp_path,
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
    expected = value if Path(value).is_absolute() else str(tmp_path / value)
    assert json.loads(result.stdout)["SQLITE_DATABASE_PATH"] == expected


@pytest.mark.parametrize(
    ("task", "arguments"),
    [
        ("validate", ["validate"]),
        ("generate", ["generate"]),
        ("makemigrations", ["migrate", "dev", "--create-only", "--name", "new fields"]),
        ("migrate", ["migrate", "deploy"]),
        ("status", ["migrate", "status"]),
        ("format", ["format"]),
    ],
)
def test_data_access_tasks_use_local_cli_and_explicit_actions(tmp_path, task, arguments):
    binary = tmp_path / "bin"
    binary.mkdir()
    tool = binary / "bunx"
    tool.write_text(
        f'#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["CALL_LOG"]).write_text(json.dumps([os.getcwd(),sys.argv[1:]]))\n'
    )
    tool.chmod(0o755)
    project = tmp_path / "javascript directory"
    project.mkdir()
    log = tmp_path / "calls.json"
    artifact = Catalog(BOX).render(["prisma", "sqlite"])[f"task.prisma:{task}"]
    assert isinstance(artifact.content, bytes)
    script = tomllib.loads(artifact.content.decode())["tasks"][f"prisma:{task}"]["run"]
    result = subprocess.run(
        ["/bin/sh", "-c", script],
        env={
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "CALL_LOG": str(log),
            "PROJECT_JAVASCRIPT_DIRECTORY": str(project),
            "PRISMA_CONFIG": "config with spaces.ts",
            "usage_name": "new fields",
        },
    )
    assert result.returncode == 0
    directory, actual = json.loads(log.read_text())
    assert Path(directory) == project.resolve()
    assert actual == [
        "--bun",
        "--no-install",
        "prisma",
        *arguments,
        "--config",
        "config with spaces.ts",
    ]


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="SQLite CLI not installed")
def test_sqlite_prepare_uses_initialization_sql_and_preserves_existing_database(tmp_path):
    target = tmp_path / "nested directory" / "application.sqlite3"
    initial = tmp_path / "initial.sql"
    initial.write_text("CREATE TABLE example(value TEXT); INSERT INTO example VALUES ('initial');")
    env = {
        **os.environ,
        "DATABASE_EXECUTION_MODE": "native",
        "SQLITE_DATABASE_PATH": str(target),
        "SQLITE_INIT_SQL": str(initial),
    }
    command = ["/bin/sh", "-eu", str(BOX / "tasks/sqlite-prepare.sh")]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM example").fetchone() == ("initial",)
    original = target.read_bytes()
    assert subprocess.run(command, env=env, capture_output=True).returncode == 2
    assert target.read_bytes() == original


@pytest.mark.parametrize("runner", ["pytest", "unittest"])
@pytest.mark.parametrize("absolute", [False, True])
def test_python_tests_discover_sibling_tests_outside_sources(tmp_path, runner, absolute):
    project = tmp_path / "python project"
    source = project / "src"
    tests = project / "custom tests"
    source.mkdir(parents=True)
    tests.mkdir()
    test_file = tests / "test_example.py"
    test_file.write_text(
        "import unittest\nclass Example(unittest.TestCase):\n"
        "    def test_value(self):\n        self.assertEqual(1, 1)\n"
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text(
        f"#!{sys.executable}\nimport os,sys\n"
        "args=sys.argv[2:]\n"
        "if args[0]=='pytest': args=['-m','pytest',*args[1:]]\n"
        "elif args[0]=='python': args=args[1:]\n"
        f"os.execv({sys.executable!r},[{sys.executable!r},*args])\n"
    )
    uv.chmod(0o755)
    content = Catalog(BOX).render([runner])["task.test"].content
    assert isinstance(content, bytes)
    script = tomllib.loads(content.decode())["tasks"]["test"]["run"]
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "PYTHON_SOURCE": str(source),
        "PROJECT_ROOT": str(project),
        "PYTHON_TESTS": str(tests) if absolute else "custom tests",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    result = subprocess.run(
        ["/bin/sh", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout if runner == "pytest" else "Ran 1 test" in result.stderr
    test_file.write_text(test_file.read_text().replace("assertEqual(1, 1)", "assertEqual(1, 200)"))
    result = subprocess.run(
        ["/bin/sh", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0


@pytest.mark.parametrize("component", ["python-package", "nuitka"])
def test_optional_python_build_uses_project_directory_and_preserves_failure(tmp_path, component):
    from kitflow.catalog import KitFlowError
    from kitflow.wizard import Wizard

    catalog = Catalog(BOX)
    assert "task.build" not in catalog.render(["python"])
    with pytest.raises(KitFlowError, match="[Cc]onflict"):
        catalog.render(["python-package", "nuitka"])
    model = Wizard(catalog, ["python"], [], existing=True)
    step = next(s for s in model.steps() if s.id == "build-tools")
    model.enter(step)
    assert not {"python-package", "nuitka"} & model.chosen
    model.toggle(component)
    assert component in model.chosen
    model.toggle(component)
    assert not {"python-package", "nuitka"} & model.chosen
    project = tmp_path / "python project"
    project.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls.json"
    uv = binary / "uv"
    uv.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        'Path(os.environ["CALL_LOG"]).write_text(json.dumps([os.getcwd(),sys.argv[1:]]))\n'
        'sys.exit(int(os.environ.get("FAIL_CODE","0")))\n'
    )
    uv.chmod(0o755)
    content = catalog.render([component])["task.build"].content
    assert isinstance(content, bytes)
    script = tomllib.loads(content.decode())["tasks"]["build"]["run"]
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "PROJECT_ROOT": str(project),
        "CALL_LOG": str(log),
        "PYTHON_ENTRYPOINT": "app files/main.py",
        "PYTHON_BUILD_DIRECTORY": "build output",
    }
    result = subprocess.run(["/bin/sh", "-c", script], env=env)
    assert result.returncode == 0
    directory, args = json.loads(log.read_text())
    assert Path(directory) == project.resolve()
    assert args == (
        ["build"]
        if component == "python-package"
        else [
            "run",
            "--no-sync",
            "python",
            "-m",
            "nuitka",
            "--mode=standalone",
            "--output-dir=build output",
            "app files/main.py",
        ]
    )
    result = subprocess.run(["/bin/sh", "-c", script], env={**env, "FAIL_CODE": "7"})
    assert result.returncode == 7


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise not installed")
def test_standard_quiet_defaults_hide_command_echo_but_keep_tool_output(tmp_path):
    config = (BOX / "settings/base.toml").read_text()
    (tmp_path / ".env").write_text("")
    (tmp_path / "mise.toml").write_text(config + '\n[tasks.example]\nrun = "echo tool-output"\n')
    result = subprocess.run(
        ["mise", "--cd", str(tmp_path), "run", "example"],
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
    assert result.stdout.strip() == "tool-output"
    assert "$ echo" not in result.stderr


def test_python_source_defaults_upgrade_without_replacing_user_source_path(tmp_path):
    from kitflow.engine import apply, load_config, plan

    old = Catalog(BOX)
    old.data["defaults"] = [
        row for row in old.data["defaults"] if row["id"] not in {"python-project", "python-tests"}
    ]
    apply(plan(tmp_path, old, ["pytest"], load_config(tmp_path)), {})
    path = tmp_path / "mise.toml"
    path.write_text(path.read_text().replace('python_source = "."', 'python_source = "src"'))
    apply(plan(tmp_path, Catalog(BOX), ["pytest"], load_config(tmp_path)), {})
    data = tomllib.loads(path.read_text())
    assert data["vars"]["python_source"] == "src"
    assert data["vars"]["project_root"] == "."
    assert data["vars"]["python_tests"] == "tests"
    assert "PROJECT_ROOT" in data["env"]


@pytest.mark.skipif(shutil.which("mise") is None, reason="mise not installed")
@pytest.mark.parametrize("override", ["relative", "absolute", "dotenv"])
def test_python_path_settings_resolve_sources_from_project_root(tmp_path, override):
    import tomlkit

    from kitflow.engine import apply, load_config, plan

    backend = tmp_path / "nested backend"
    backend.mkdir()
    source = backend / "source files"
    source.mkdir()
    apply(plan(tmp_path, Catalog(BOX), ["pytest"], load_config(tmp_path)), {})
    path = tmp_path / "mise.toml"
    data = tomlkit.parse(path.read_text())
    data["vars"]["project_root"] = str(backend) if override == "absolute" else "nested backend"
    data["vars"]["python_source"] = str(source) if override == "absolute" else "source files"
    data["vars"]["python_tests"] = "test files"
    data["tasks"]["paths"] = {
        "run": 'printf \'%s\\n\' "$PROJECT_ROOT" "$PYTHON_SOURCE" "$PYTHON_TESTS"'
    }
    path.write_text(tomlkit.dumps(data))
    (tmp_path / ".env").write_text(
        f'PROJECT_ROOT="{backend}"\nPYTHON_SOURCE="{source}"\nPYTHON_TESTS="{backend / "external tests"}"\n'
        if override == "dotenv"
        else ""
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PROJECT_ROOT", "PYTHON_SOURCE", "PYTHON_TESTS"}
    }
    result = subprocess.run(
        ["mise", "--cd", str(tmp_path), "run", "paths"],
        env={
            **env,
            "MISE_TRUSTED_CONFIG_PATHS": str(tmp_path),
            "MISE_CACHE_DIR": str(tmp_path / "cache"),
            "MISE_STATE_DIR": str(tmp_path / "state"),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    root_value, source_value, tests_value = result.stdout.strip().splitlines()
    assert Path(root_value).resolve() == backend.resolve()
    assert Path(source_value).resolve() == source.resolve()
    assert tests_value == (
        str(backend / "external tests") if override == "dotenv" else "test files"
    )
