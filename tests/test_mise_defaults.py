import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from kitflow import mise
from kitflow.catalog import Catalog, KitFlowError
from kitflow.engine import apply, load_config, plan


@pytest.fixture
def catalog_path(tmp_path):
    root = tmp_path / "box"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", root)
    (root / "settings.toml").write_text(
        '[vars]\npython_source="."\nport=8000\n[env]\nPYTHON_SOURCE="{{ config_root }}/{{ vars.python_source }}"\n'
    )
    with (root / "kitflow-box.toml").open("a") as stream:
        stream.write('[[defaults]]\nid="python"\ntemplate="settings.toml"\nwhen=["python"]\n')
    return root


def test_deselect_removes_seeded_defaults_even_after_edit(catalog_path, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "mise.toml"
    path.write_text("# User settings\n[vars]\nport=9000\n")
    catalog = Catalog(catalog_path)
    apply(plan(project, catalog, ["python", "ruff"], load_config(project)), {})
    data = tomllib.loads(path.read_text())
    assert data["vars"]["port"] == 9000
    assert data["vars"]["python_source"] == "."
    assert "# User settings" in path.read_text()
    path.write_text(path.read_text().replace('python_source = "."', 'python_source = "backend"'))
    (catalog_path / "settings.toml").write_text('[vars]\npython_source="changed"\nport=9999\n')
    catalog = Catalog(catalog_path)
    assert not plan(project, catalog, ["python", "ruff"], load_config(project)).changes
    apply(plan(project, catalog, [], load_config(project)), {})
    data = tomllib.loads(path.read_text())
    assert data["vars"] == {"port": 9000}
    assert "PYTHON_SOURCE" not in data["env"]
    apply(plan(project, catalog, ["python"], load_config(project)), {})
    assert tomllib.loads(path.read_text())["vars"]["python_source"] == "changed"


def test_deselect_preserves_shared_defaults_and_untracked_keys(catalog_path, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "mise.toml"
    (catalog_path / "shared.toml").write_text('[vars]\npython_source="."\n')
    with (catalog_path / "kitflow-box.toml").open("a") as stream:
        stream.write('[[defaults]]\nid="shared"\ntemplate="shared.toml"\nwhen=["agents"]\n')
    catalog = Catalog(catalog_path)
    apply(plan(project, catalog, ["python", "agents"], load_config(project)), {})
    apply(plan(project, catalog, ["agents"], load_config(project)), {})
    assert tomllib.loads(path.read_text())["vars"] == {"python_source": "."}

    legacy = load_config(project)
    del legacy["state"]["seeded_mise_keys"]
    apply(plan(project, catalog, [], legacy), {})
    assert tomllib.loads(path.read_text())["vars"] == {"python_source": "."}


def test_defaults_never_add_tools(catalog_path):
    (catalog_path / "settings.toml").write_text('[tools]\npython="latest"\n')
    with pytest.raises(KitFlowError, match="only vars, env and settings"):
        Catalog(catalog_path)


def test_skipped_translation_task_keeps_settings_until_task_is_removed(tmp_path):
    box = Catalog(Path(__file__).resolve().parents[1] / "box")
    retained = ["javascript", "bun", "vscode-extension"]
    apply(plan(tmp_path, box, [*retained, "script-i18n"], load_config(tmp_path)), {})
    path = tmp_path / "mise.toml"
    path.write_text(path.read_text().replace("bun run ", "bun run --silent "))
    result = plan(tmp_path, box, retained, load_config(tmp_path))
    task = next(change for change in result.changes if change.artifact.id == "task.translations")
    assert task.conflict
    task.decision = "skip"
    apply(result, {})
    data = mise.parse(path.read_text())
    assert "translations" in data["tasks"]
    assert "I18N_SCRIPT" in data["env"]
    assert "i18n_script" in data["vars"]

    result = plan(tmp_path, box, retained, load_config(tmp_path))
    for change in result.changes:
        change.decision = "apply"
    apply(result, {})
    data = mise.parse(path.read_text())
    assert "translations" not in data["tasks"]
    assert "I18N_SCRIPT" not in data["env"]
    assert "i18n_script" not in data["vars"]


@pytest.mark.parametrize("section", ["vars", "env", "settings.task"])
@pytest.mark.parametrize("merge", [mise.add_defaults, mise.reset_defaults])
def test_late_defaults_stay_outside_task_markers(section, merge):
    original = (
        f"[{section}]\nexisting = 1\n\n"
        '# kitflow:begin task.help\n[tasks.help]\nrun = "true"\n# kitflow:end task.help\n'
        '\n# kitflow:begin task.test\n[tasks.test]\nrun = "true"\n# kitflow:end task.test\n'
    )
    result = merge(original, f"[{section}]\nnew = 2\n".encode())
    settings = tomllib.loads(result)
    for key in section.split("."):
        settings = settings[key]
    assert settings == {"existing": 1, "new": 2}
    assert (
        result[result.index("# kitflow:begin") :] == original[original.index("# kitflow:begin") :]
    )


def test_fragment_directory_and_task_metadata(catalog_path, tmp_path):
    with (catalog_path / "kitflow-box.toml").open("a") as stream:
        stream.write(
            '[[tasks]]\nid="example"\nname="example"\ntemplate="example.sh"\nwhen=[]\ndirectory_env="PROJECT_DIRECTORY"\ndescription="Example task"\nalias="default"\nquiet=true\nusage=\'arg "[name]"\'\n'
        )
    (catalog_path / "example.sh").write_text('printf "%s" "$PWD"')
    artifact = Catalog(catalog_path).render([])["task.example"]
    assert isinstance(artifact.content, bytes)
    task = tomllib.loads(artifact.content.decode())["tasks"]["example"]
    assert task["alias"] == "default"
    assert task["quiet"] is True
    folder = tmp_path / "path with spaces"
    folder.mkdir()
    import os

    result = subprocess.run(
        ["/bin/sh", "-c", task["run"]],
        env={**os.environ, "PROJECT_DIRECTORY": str(folder)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert Path(result.stdout) == folder.resolve()
    result = subprocess.run(
        ["/bin/sh", "-c", task["run"]],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "PROJECT_DIRECTORY" in result.stderr


def test_existing_defaults_are_adopted_without_recreating_deleted_user_values(
    catalog_path, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "mise.toml"
    path.write_text((catalog_path / "settings.toml").read_text())
    catalog = Catalog(catalog_path)
    apply(plan(project, catalog, ["python"], load_config(project)), {})
    path.write_text(path.read_text().replace("port=8000\n", ""))
    assert not plan(project, catalog, ["python"], load_config(project)).changes


def test_alternative_conditions_are_combined_with_required_components(catalog_path):
    with (catalog_path / "kitflow-box.toml").open("a") as stream:
        stream.write(
            '[[tasks]]\nid="conditional"\nname="conditional"\ntemplate="example.sh"\nwhen=["python"]\nwhen_any=["ruff", "django"]\n'
        )
    (catalog_path / "example.sh").write_text("echo example")
    catalog = Catalog(catalog_path)
    assert "task.conditional" not in catalog.render(["python"])
    assert "task.conditional" in catalog.render(["ruff"])


def test_exclusions_disable_matching_files_and_tasks(catalog_path):
    with (catalog_path / "kitflow-box.toml").open("a") as stream:
        stream.write(
            '[[files]]\nid="starter"\npath="starter.txt"\ntemplate="example.sh"\n'
            'when=["python"]\nwhen_not=["ruff"]\n'
            '[[tasks]]\nid="starter"\nname="starter"\ntemplate="example.sh"\n'
            'when=["python"]\nwhen_not=["ruff"]\n'
        )
    (catalog_path / "example.sh").write_text("echo example")
    catalog = Catalog(catalog_path)
    assert {"starter", "task.starter"} <= catalog.render(["python"]).keys()
    assert not {"starter", "task.starter"}.intersection(catalog.render(["ruff"]))


@pytest.mark.parametrize("absolute_paths", [False, True])
def test_generated_python_paths_are_normalized(tmp_path, absolute_paths):
    import json
    import os

    if not shutil.which("mise"):
        pytest.skip("mise is not installed")
    project = tmp_path / "project with spaces"
    project.mkdir()
    catalog = Catalog(Path(__file__).parents[1] / "box")
    apply(plan(project, catalog, ["python", "pytest", "nuitka"], load_config(project)), {})
    path = project / "mise.toml"
    text = path.read_text()
    assert "# Relative to mise.toml" in text
    assert "# Entry file, relative to project_root." in text
    root = project / "backend"
    source = root / "missing" / "src"
    import tomlkit

    document = tomlkit.parse(text)
    document["vars"]["project_root"] = str(root) if absolute_paths else "./backend/."
    document["vars"]["python_source"] = str(source) if absolute_paths else "./missing/src/."
    path.write_text(tomlkit.dumps(document))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MISE_")}
    for key in ("PROJECT_ROOT", "PYTHON_SOURCE", "PYTHON_TESTS"):
        environment.pop(key, None)
    environment["MISE_TRUSTED_CONFIG_PATHS"] = str(project)
    environment["MISE_STATE_DIR"] = str(tmp_path / "mise-state")
    result = subprocess.run(
        ["mise", "env", "--json"], cwd=project, env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values["PROJECT_ROOT"] == str(root)
    assert values["PYTHON_SOURCE"] == str(source)
