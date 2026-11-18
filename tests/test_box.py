from pathlib import Path

from kitflow.catalog import Catalog
from kitflow.engine import apply, load_config, plan


def test_example_box_builds_basic_python_project(tmp_path):
    root = Path(__file__).parents[1] / "box"
    catalog = Catalog(root)
    selected = ["python", "ruff", "ty", "rumdl", "agents"]
    apply(plan(tmp_path, catalog, selected, load_config(tmp_path)), {"local": str(root)})
    assert (tmp_path / "PROJECT.md").read_bytes() == b""
    assert (tmp_path / "README.md").read_bytes() == b""
    assert (tmp_path / "ruff.toml").exists()
    assert not plan(tmp_path, catalog, selected, load_config(tmp_path)).changes


def test_environment_files_are_optional_and_local_values_are_preserved(tmp_path):
    root = Path(__file__).parents[1] / "box"
    catalog = Catalog(root)
    example = tmp_path / ".env.example"
    local = tmp_path / ".env"

    def configure(selected):
        result = plan(tmp_path, catalog, selected, load_config(tmp_path))
        apply(result, {"local": str(root)})

    configure(["python"])
    configure(["python"])
    assert not example.exists()
    assert not local.exists()

    configure(["python", "env-local"])
    assert local.read_bytes() == b""
    assert not example.exists()
    local.write_text("LOCAL_VALUE=custom\n")

    configure(["python", "env-example"])
    assert example.is_file()
    assert local.read_text() == "LOCAL_VALUE=custom\n"
    review = plan(tmp_path, catalog, ["python", "env-local"], load_config(tmp_path), reset=True)
    assert all(change.artifact.path != ".env" for change in review.changes)

    configure(["python"])
    assert not example.exists()
    assert local.read_text() == "LOCAL_VALUE=custom\n"


def test_standard_check_runs_only_checks_and_preserves_failure_status(tmp_path):
    import os
    import subprocess

    catalog = Catalog(Path(__file__).parents[1] / "box")
    artifacts = catalog.render(list(catalog.components), check_conflicts=False)
    artifact = artifacts["task.check"]
    import tomllib

    assert isinstance(artifact.content, bytes)
    script = tomllib.loads(artifact.content.decode())["tasks"]["check"]["run"]
    task_scripts = tmp_path / "task-scripts"
    task_scripts.mkdir()
    for value in artifacts.values():
        if value.kind == "task":
            assert isinstance(value.content, bytes)
            run = tomllib.loads(value.content.decode())["tasks"][value.key]["run"]
            (task_scripts / f"{value.key}.sh").write_text(run)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "commands"
    for command in (
        "ruff",
        "rumdl",
        "ty",
        "mypy",
        "bun",
        "bunx",
        "npm",
        "cargo",
        "uv",
        "djlint",
        "swift",
        "swiftlint",
        "xcodebuild",
    ):
        path = binaries / command
        path.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$0 $*" >> "$COMMAND_LOG"\n'
            'if [ "$(basename "$0")" = "$FAIL_TOOL" ]; then exit 7; fi\n'
        )
        path.chmod(0o755)
    mise = binaries / "mise"
    mise.write_text(
        '#!/bin/sh\nprintf "mise %s\\n" "$3" >> "$COMMAND_LOG"\nif [ "$3" = _swift ]; then export usage_action="$4" usage_configuration="$5"; fi\nexec /bin/sh "$TASK_SCRIPTS/$3.sh"\n'
    )
    mise.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "COMMAND_LOG": str(log),
        "FAIL_TOOL": "",
        "TASK_SCRIPTS": str(task_scripts),
        "PYTHON_SOURCE": str(tmp_path),
        "PROJECT_JAVASCRIPT_DIRECTORY": str(tmp_path),
        "PROJECT_RUST_DIRECTORY": str(tmp_path),
        "PROJECT_SWIFT_DIRECTORY": str(tmp_path),
        "SWIFT_BACKEND": "swiftpm",
    }
    result = subprocess.run(["/bin/sh", "-c", script], cwd=tmp_path, env=env)
    assert result.returncode == 0
    commands = log.read_text()
    assert "--fix" not in commands
    assert "--reformat" not in commands
    assert "--dry-run" in commands
    assert "--no-pretty" in commands
    assert all(tool in commands for tool in ("ruff", "rumdl", "ty", "bun", "cargo", "djlint"))
    log.unlink()
    result = subprocess.run(
        ["/bin/sh", "-c", script], cwd=tmp_path, env={**env, "FAIL_TOOL": "ruff"}
    )
    assert result.returncode == 7
    assert len(log.read_text().splitlines()) == 2
    log.unlink()
    (task_scripts / "lint.sh").write_text('echo custom-lint >> "$COMMAND_LOG"\n')
    result = subprocess.run(["/bin/sh", "-c", script], cwd=tmp_path, env=env)
    assert result.returncode == 0
    assert log.read_text().count("custom-lint") == 1
    assert "ruff check" not in log.read_text()
