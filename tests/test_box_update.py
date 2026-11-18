import shutil
from pathlib import Path

import pytest

from kitflow import box_update, cli, settings
from kitflow.catalog import Catalog, KitFlowError


@pytest.fixture
def boxes(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures/catalog"
    destination = tmp_path / "local"
    incoming = tmp_path / "remote"
    shutil.copytree(fixture, destination / "default")
    (destination / "kitflow-box.toml").write_text("schema = 1\n")
    box_update.prepare_user_directories(destination)
    shutil.copytree(fixture, incoming)
    (incoming / "templates/ruff.toml").write_text("line-length = 120\n")
    monkeypatch.setattr(box_update, "seed_box", lambda path: shutil.copytree(incoming, path))
    return destination, incoming


def test_update_replaces_standard_and_preserves_user_files_and_projects(boxes, tmp_path):
    destination, incoming = boxes
    (destination / "templates/ruff.toml").write_text("line-length = 140\n")
    (destination / "personal.md").write_text("Personal")
    (destination / "default/obsolete.md").write_text("Old")
    (incoming / "new.md").write_text("New")
    project = tmp_path / "project"
    project.mkdir()
    (project / "ruff.toml").write_text("Project")
    before_user = box_update.snapshot_user(destination)
    reviews = []
    assert (
        box_update.refresh_box(
            destination, lambda before, after: reviews.append((before, after)) or True
        )
        == 3
    )
    assert len(reviews) == 1
    assert not (destination / "default/obsolete.md").exists()
    assert (destination / "default/new.md").read_text() == "New"
    assert box_update.snapshot_user(destination) == before_user
    assert Catalog(destination).render(["ruff"])["ruff"].content == b"line-length = 140\n"
    assert (project / "ruff.toml").read_text() == "Project"


def test_declining_update_keeps_entire_box(boxes):
    destination, _ = boxes
    before = box_update.snapshot(destination)
    assert box_update.refresh_box(destination, lambda *_: False) == 0
    assert box_update.snapshot(destination) == before


def test_invalid_standard_does_not_write_any_changes(boxes):
    destination, incoming = boxes
    (incoming / "templates/ruff.toml").unlink()
    before = box_update.snapshot(destination)
    with pytest.raises(KitFlowError):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before


def test_failed_publish_rolls_back_standard(boxes, monkeypatch):
    destination, _ = boxes
    before = box_update.snapshot(destination)
    original = Path.rename

    def fail_publish(path, target):
        if path.name == "incoming":
            raise OSError("disk failure")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="disk failure"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before


@pytest.mark.parametrize("layer", ["default/", ""])
def test_edit_during_review_cancels_update(boxes, layer):
    destination, _ = boxes

    def edit(*_):
        (destination / f"{layer}templates/ruff.toml").write_text("line-length = 150\n")
        return True

    with pytest.raises(KitFlowError, match="changed during"):
        box_update.refresh_box(destination, edit)
    assert (destination / f"{layer}templates/ruff.toml").read_text() == "line-length = 150\n"


def test_bare_startup_keeps_existing_box_without_prompts(boxes, monkeypatch):
    destination, _ = boxes
    shutil.copytree(destination, settings.box_path())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        cli, "choose_action", lambda *_args, **_kwargs: pytest.fail("Unexpected prompt")
    )
    before = box_update.snapshot(settings.box_path())
    assert cli.run(cli.parser().parse_args([])) == 0
    assert box_update.snapshot(settings.box_path()) == before


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("options", [[], ["-y"]])
def test_explicit_update_applies_without_diffs_or_prompts(
    boxes, monkeypatch, capsys, interactive, options
):
    destination, _ = boxes
    shutil.copytree(destination, settings.box_path())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: interactive)
    monkeypatch.setattr(
        cli, "choose_action", lambda *_args, **_kwargs: pytest.fail("Unexpected prompt")
    )
    monkeypatch.setattr(cli, "Syntax", lambda *_args, **_kwargs: pytest.fail("Unexpected diff"))
    assert cli.run(cli.parser().parse_args(["upgrade", *options])) == 0
    assert (
        settings.box_path() / "default/templates/ruff.toml"
    ).read_text() == "line-length = 120\n"
    output = capsys.readouterr().out
    assert "Standard box files changed: 1" in output
    assert "uses schema 1" in " ".join(output.split())
    assert "manually" in output
    assert "incoming/" not in output


def test_failed_download_does_not_change_box(boxes, monkeypatch):
    destination, _ = boxes
    before = box_update.snapshot(destination)

    def disconnected(_):
        raise KitFlowError("Cannot download box")

    monkeypatch.setattr(box_update, "seed_box", disconnected)
    with pytest.raises(KitFlowError, match="Cannot download"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before
    assert not list(destination.parent.glob(".box-refresh-*"))


def test_legacy_box_migration_preserves_every_user_file(boxes, tmp_path):
    _, incoming = boxes
    legacy = tmp_path / "legacy"
    shutil.copytree(incoming, legacy)
    (legacy / "templates/ruff.toml").write_text("line-length = 150\n")
    before = box_update.snapshot(legacy)
    assert box_update.refresh_box(legacy, lambda *_: True) > 0
    assert box_update.snapshot_user(legacy) == before
    assert (legacy / "default/kitflow-box.toml").exists()
    assert Catalog(legacy).render(["ruff"])["ruff"].content == b"line-length = 150\n"


def test_new_standard_incompatible_with_override_keeps_old_box(boxes):
    destination, incoming = boxes
    with (destination / "kitflow-box.toml").open("a") as stream:
        stream.write('[disabled]\nfiles=["ruff"]\n')
    manifest = incoming / "kitflow-box.toml"
    manifest.write_text(manifest.read_text().replace('id = "ruff"\npath', 'id = "new-ruff"\npath'))
    before = box_update.snapshot(destination)
    with pytest.raises(KitFlowError, match="Unknown disabled"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before


def test_invalid_standard_syntax_is_rejected_even_when_user_overrides_it(boxes):
    destination, incoming = boxes
    (destination / "templates/ruff.toml").write_text("line-length = 100")
    (incoming / "templates/ruff.toml").write_text("broken = [")
    before = box_update.snapshot(destination)
    with pytest.raises(KitFlowError, match="Invalid standard box update"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before


def test_update_is_idempotent(boxes):
    destination, _ = boxes
    assert box_update.refresh_box(destination, lambda *_: True) == 1
    assert box_update.refresh_box(destination, lambda *_: pytest.fail("No changes to review")) == 0


def test_snapshots_ignore_finder_metadata_in_all_layers(boxes):
    destination, _ = boxes
    before = box_update.snapshot(destination)
    for directory in (destination, destination / "default", destination / "templates"):
        (directory / ".DS_Store").write_bytes(b"Finder metadata")
    assert box_update.snapshot(destination) == before
    assert box_update.refresh_box(destination, lambda *_: True) == 1
    assert (destination / ".DS_Store").exists()
    assert (destination / "templates/.DS_Store").exists()
    assert not (destination / "default/.DS_Store").exists()


def test_upgrade_rejects_project_actions():
    for arguments in (["upgrade", "-c", "python"], ["upgrade", "-i"]):
        with pytest.raises(KitFlowError, match="upgrade does not accept project actions"):
            cli.run(cli.parser().parse_args(arguments))


def test_old_box_subcommand_is_removed():
    with pytest.raises(SystemExit) as error:
        cli.parser().parse_args(["box", "update"])
    assert error.value.code == 2
