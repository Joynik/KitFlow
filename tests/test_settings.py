import shutil
from pathlib import Path

from kitflow import cli, settings, source
from kitflow.engine import load_config


def test_user_box_location(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert settings.config_directory() == tmp_path / "kitflow"
    assert settings.box_path() == tmp_path / "kitflow"
    assert cli.run(cli.parser().parse_args(["config"])) == 0
    assert not settings.config_directory().exists()


def test_project_updates_use_shared_local_box_without_network(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures/catalog"
    shutil.copytree(fixture, settings.box_path())

    def network_forbidden(_url):
        raise AssertionError("Project operations must not contact GitHub after bootstrap")

    monkeypatch.setattr(source, "fetch", network_forbidden)
    projects = [tmp_path / "one", tmp_path / "two"]
    for project in projects:
        project.mkdir()
        args = ["init", "--components", "python,ruff", "--yes", "--project", str(project)]
        assert cli.run(cli.parser().parse_args(args)) == 0
        assert load_config(project)["source"] == {"kind": "user-box"}
    (settings.box_path() / "templates/ruff.toml").write_text("line-length = 120\n")
    for project in projects:
        args = ["update", "--yes", "--project", str(project)]
        assert cli.run(cli.parser().parse_args(args)) == 0
        assert (project / "ruff.toml").read_text() == "line-length = 120\n"


def test_existing_remote_metadata_does_not_select_a_remote_source(tmp_path, monkeypatch):
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", settings.box_path())
    project = tmp_path / "project"
    project.mkdir()
    assert (
        cli.run(
            cli.parser().parse_args(
                [
                    "init",
                    "--components",
                    "python",
                    "--yes",
                    "--project",
                    str(project),
                ]
            )
        )
        == 0
    )
    path = project / "kitflow.toml"
    path.write_text(
        path.read_text().replace('kind = "user-box"', 'repository = "old/source"\nref = "main"')
    )

    def network_forbidden(_url):
        raise AssertionError("Legacy project metadata must not trigger remote requests")

    monkeypatch.setattr(source, "fetch", network_forbidden)
    assert cli.run(cli.parser().parse_args(["update", "--yes", "--project", str(project)])) == 0
    assert load_config(project)["source"] == {"kind": "user-box"}
