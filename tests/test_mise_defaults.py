import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from kitflow.catalog import Catalog, KitFlowError
from kitflow.engine import apply, load_config, plan


@pytest.fixture
def catalog_path(tmp_path):
    root = tmp_path / "box"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", root)
    (root / "settings.toml").write_text(
        '[vars]\npython_directory="."\nport=8000\n[env]\nPROJECT_PYTHON_DIRECTORY="{{ config_root }}/{{ vars.python_directory }}"\n'
    )
    with (root / "kitflow-box.toml").open("a") as stream:
        stream.write('[[defaults]]\nid="python"\ntemplate="settings.toml"\nwhen=["python"]\n')
    return root


def test_defaults_are_user_owned_across_updates_and_component_removal(catalog_path, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = project / "mise.toml"
    path.write_text("# User settings\n[vars]\nport=9000\n")
    catalog = Catalog(catalog_path)
    apply(plan(project, catalog, ["python", "ruff"], load_config(project)), {})
    data = tomllib.loads(path.read_text())
    assert data["vars"]["port"] == 9000
    assert data["vars"]["python_directory"] == "."
    assert "# User settings" in path.read_text()
    path.write_text(
        path.read_text().replace('python_directory = "."', 'python_directory = "backend"')
    )
    (catalog_path / "settings.toml").write_text('[vars]\npython_directory="changed"\nport=9999\n')
    catalog = Catalog(catalog_path)
    assert not plan(project, catalog, ["python", "ruff"], load_config(project)).changes
    apply(plan(project, catalog, [], load_config(project)), {})
    assert tomllib.loads(path.read_text())["vars"]["python_directory"] == "backend"
    assert tomllib.loads(path.read_text())["vars"]["port"] == 9000


def test_defaults_never_add_tools(catalog_path):
    (catalog_path / "settings.toml").write_text('[tools]\npython="latest"\n')
    with pytest.raises(KitFlowError, match="only vars, env and settings"):
        Catalog(catalog_path)


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
