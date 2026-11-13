import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kitflow import source
from kitflow.catalog import Catalog
from kitflow.check import configuration_issues
from kitflow.engine import apply, load_config, plan
from kitflow.settings import box_path


@pytest.fixture
def configurations(tmp_path):
    box = tmp_path / "box"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", box)
    project = tmp_path / "project"
    project.mkdir()
    catalog = Catalog(box)
    apply(plan(project, catalog, ["ruff"], load_config(project)), {"local": str(box)})
    return box, project


def snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_valid_box_and_project_check_is_read_only(configurations, monkeypatch):
    box, project = configurations
    before = snapshot(project), snapshot(box)
    monkeypatch.setattr(source, "fetch", lambda *_args: pytest.fail("check must work offline"))
    assert configuration_issues(box, project) == []
    assert (snapshot(project), snapshot(box)) == before


def test_valid_manual_changes_are_not_configuration_errors(configurations):
    box, project = configurations
    (project / "ruff.toml").write_text("line-length = 120\n")
    assert configuration_issues(box, project) == []


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ('\n[[files]]\nid="extra"\npath="extra.toml"\ntemplat="missing.toml"\n', "Unknown fields"),
        ('\n[[files]]\nid="extra"\npath="extra.toml"\ntemplate="missing.toml"\n', "missing.toml"),
        (
            '\n[[components]]\nid="broken"\nlabel="Broken"\ncategory="Checks"\nrequires=["unknown"]\n',
            "Unknown dependency",
        ),
    ],
)
def test_box_rule_errors_are_reported(configurations, extra, message):
    box, project = configurations
    manifest = box / "kitflow-box.toml"
    manifest.write_text(manifest.read_text() + extra)
    issues = configuration_issues(box, project)
    assert any(path == manifest and message in error for path, error in issues)


def test_template_and_project_syntax_errors_are_reported_together(configurations):
    box, project = configurations
    template = box / "templates/ruff.toml"
    template.write_text("broken = [")
    config = project / "kitflow.toml"
    config.write_text("broken = [")
    paths = {path for path, _error in configuration_issues(box, project)}
    assert template in paths
    assert config in paths


@pytest.mark.parametrize(
    "contents",
    [
        'schema=1\n[selection]\ncomponents=["unknown"]\n',
        'schema=1\n[selection]\ncomponent=["python"]\n',
        'schema=1\nselection="python"\n',
        "schema=true\n[selection]\ncomponents=[]\n",
    ],
)
def test_invalid_project_configuration_is_reported(configurations, contents):
    box, project = configurations
    config = project / "kitflow.toml"
    config.write_text(contents)
    assert any(path == config for path, _error in configuration_issues(box, project))


def test_project_toml_and_mise_markers_are_validated(configurations):
    box, project = configurations
    (project / "ruff.toml").write_text("broken = [")
    (project / "mise.toml").write_text("# kitflow:begin task.orphan\n")
    paths = {path for path, _error in configuration_issues(box, project)}
    assert project / "ruff.toml" in paths
    assert project / "mise.toml" in paths


def test_check_command_does_not_create_or_download_a_missing_box(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "kitflow", "check", "-p", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Check failed" in result.stdout
    assert not box_path().exists()


def test_check_command_supports_box_and_project_overrides(configurations):
    box, project = configurations
    result = subprocess.run(
        [sys.executable, "-m", "kitflow", "check", "-b", str(box), "-p", str(project)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Configuration checks passed" in result.stdout
    assert result.stderr == ""


def test_box_only_check_skips_a_directory_without_project_configuration(tmp_path):
    box = Path(__file__).parent / "fixtures/catalog"
    assert configuration_issues(box, tmp_path) == []


def test_json_syntax_is_checked_for_templates_and_extensionless_project_files(configurations):
    box, project = configurations
    manifest = box / "kitflow-box.toml"
    manifest.write_text(
        manifest.read_text()
        + '\n[[files]]\nid="json"\npath=".settings"\ntemplate="templates/settings.json"\n'
    )
    template = box / "templates/settings.json"
    template.write_text('{"enabled": true}')
    target = project / ".settings"
    target.write_text("{broken}")
    assert any(path == target for path, _error in configuration_issues(box, project))
    template.write_text("{broken}")
    assert any(path == template for path, _error in configuration_issues(box, project))
