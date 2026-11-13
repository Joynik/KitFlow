import shutil
from pathlib import Path

import pytest

from kitflow import box_update, cli, settings
from kitflow.catalog import KitFlowError


@pytest.fixture
def boxes(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures/catalog"
    destination = tmp_path / "local"
    incoming = tmp_path / "remote"
    shutil.copytree(fixture, destination)
    shutil.copytree(fixture, incoming)
    (incoming / "templates/ruff.toml").write_text("line-length = 120\n")
    monkeypatch.setattr(box_update, "seed_box", lambda path: shutil.copytree(incoming, path))
    return destination, incoming


def test_refresh_reviews_changed_files_and_preserves_personal_files(boxes):
    destination, _ = boxes
    (destination / "templates/ruff.toml").write_text("# My Ruff rules\n")
    (destination / "personal.md").write_text("Private standards\n")
    decisions = []

    def accept(name, before, after):
        decisions.append((name, before, after))
        return True

    assert box_update.refresh_box(destination, accept) == 1
    assert decisions == [("templates/ruff.toml", b"# My Ruff rules\n", b"line-length = 120\n")]
    assert (destination / "personal.md").read_text() == "Private standards\n"
    assert (destination / "templates/ruff.toml").read_text() == "line-length = 120\n"


def test_declining_all_files_leaves_the_box_unchanged(boxes):
    destination, _ = boxes
    before = (destination / "templates/ruff.toml").read_bytes()
    assert box_update.refresh_box(destination, lambda *_args: False) == 0
    assert (destination / "templates/ruff.toml").read_bytes() == before


def test_invalid_merged_catalog_does_not_write_any_changes(boxes):
    destination, incoming = boxes
    manifest = incoming / "kitflow-box.toml"
    manifest.write_text(manifest.read_text().replace("templates/ruff.toml", "templates/new.toml"))
    (incoming / "templates/new.toml").write_text("line-length = 120\n")
    original = (destination / "kitflow-box.toml").read_bytes()
    with pytest.raises(KitFlowError):
        box_update.refresh_box(destination, lambda name, *_args: name != "templates/new.toml")
    assert (destination / "kitflow-box.toml").read_bytes() == original
    assert not (destination / "templates/new.toml").exists()


def test_failed_write_rolls_back_previous_box_writes(boxes, monkeypatch):
    destination, incoming = boxes
    (incoming / "new.md").write_text("New file\n")
    before = (destination / "templates/ruff.toml").read_bytes()
    atomic_write = box_update.atomic_write
    attempts = 0

    def fail_second_write(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("disk failure")
        return atomic_write(*args, **kwargs)

    monkeypatch.setattr(box_update, "atomic_write", fail_second_write)
    with pytest.raises(OSError, match="disk failure"):
        box_update.refresh_box(destination, lambda *_args: True)
    assert not (destination / "new.md").exists()
    assert (destination / "templates/ruff.toml").read_bytes() == before


def test_edit_during_review_cancels_box_refresh(boxes):
    destination, _ = boxes

    def edit_during_review(*_args):
        (destination / "templates/ruff.toml").write_text("# Saved in editor\n")
        return True

    with pytest.raises(KitFlowError, match="changed during review"):
        box_update.refresh_box(destination, edit_during_review)
    assert (destination / "templates/ruff.toml").read_text() == "# Saved in editor\n"


def test_repeated_startup_offers_refresh_and_no_keeps_the_box(monkeypatch):
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", settings.box_path())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    prompts = []

    def decline(message, **_kwargs):
        prompts.append(message)
        return False

    monkeypatch.setattr(cli.Confirm, "ask", decline)
    monkeypatch.setattr(cli, "refresh_box", lambda *_args: pytest.fail("Refresh was declined"))
    assert cli.run(cli.parser().parse_args([])) == 0
    assert len(prompts) == 1


def test_repeated_startup_refreshes_only_after_both_confirmations(boxes, monkeypatch):
    destination, _ = boxes
    shutil.copytree(destination, settings.box_path())
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    prompts = []

    def accept(message, **_kwargs):
        prompts.append(message)
        return True

    monkeypatch.setattr(cli.Confirm, "ask", accept)
    assert cli.run(cli.parser().parse_args([])) == 0
    assert len(prompts) == 2
    assert (settings.box_path() / "templates/ruff.toml").read_text() == "line-length = 120\n"


def test_failed_download_does_not_change_the_box(boxes, monkeypatch):
    destination, _ = boxes
    before = (destination / "templates/ruff.toml").read_bytes()

    def disconnected(_path):
        raise KitFlowError("Cannot download box")

    monkeypatch.setattr(box_update, "seed_box", disconnected)
    with pytest.raises(KitFlowError, match="Cannot download"):
        box_update.refresh_box(destination, lambda *_args: True)
    assert (destination / "templates/ruff.toml").read_bytes() == before
    assert not list(destination.parent.glob(".box-refresh-*"))
