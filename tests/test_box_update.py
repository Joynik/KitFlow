import shutil
from pathlib import Path

import pytest

from kitflow import box_update, cli, settings, source
from kitflow.catalog import Catalog, KitFlowError
from kitflow.check import configuration_issues


@pytest.fixture
def boxes(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures/catalog"
    destination = tmp_path / "local"
    incoming = tmp_path / "remote"
    shutil.copytree(fixture, destination / "standard")
    source.prepare_user_directories(destination / "personal")
    (destination / "personal/kitflow-box.toml").write_text("schema = 1\n")
    shutil.copytree(fixture, incoming)
    (incoming / "templates/ruff.toml").write_text("line-length = 120\n")
    monkeypatch.setattr(box_update, "seed_box", lambda path: shutil.copytree(incoming, path))
    return destination, incoming


def test_update_replaces_standard_and_preserves_user_files_and_projects(boxes, tmp_path):
    destination, incoming = boxes
    (destination / "personal/templates/ruff.toml").write_text("line-length = 140\n")
    (destination / "personal/personal.md").write_text("Personal")
    (destination / "standard/obsolete.md").write_text("Old")
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
    assert not (destination / "standard/obsolete.md").exists()
    assert (destination / "standard/new.md").read_text() == "New"
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


@pytest.mark.parametrize("layer", ["standard/", "personal/"])
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
        settings.box_path() / "standard/templates/ruff.toml"
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


def test_new_standard_incompatible_with_override_keeps_old_box(boxes):
    destination, incoming = boxes
    with (destination / "personal/kitflow-box.toml").open("a") as stream:
        stream.write('[disabled]\nfiles=["ruff"]\n')
    manifest = incoming / "kitflow-box.toml"
    manifest.write_text(manifest.read_text().replace('id = "ruff"\npath', 'id = "new-ruff"\npath'))
    before = box_update.snapshot(destination)
    with pytest.raises(KitFlowError, match="Unknown disabled"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before


def test_invalid_standard_syntax_is_rejected_even_when_user_overrides_it(boxes):
    destination, incoming = boxes
    (destination / "personal/templates/ruff.toml").write_text("line-length = 100")
    (incoming / "templates/ruff.toml").write_text("broken = [")
    before = box_update.snapshot(destination)
    with pytest.raises(KitFlowError, match="Invalid standard box update"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before


def test_upgrade_checks_jsonc_and_applies_personal_validation_rules(boxes):
    destination, incoming = boxes
    template = incoming / "templates/config.json"
    template.write_text(
        '{/* comment */ "url": "https://example.com", "items": [1 /* comment */ ,],}'
    )
    with (incoming / "kitflow-box.toml").open("a") as stream:
        stream.write(
            '\n[[files]]\nid="config"\npath="config.json"\ntemplate="templates/config.json"\n'
        )
    rules = '[files]\n"templates/config.json" = "jsonc"\n'
    (incoming / "validation.toml").write_text(rules)
    personal = destination / "personal"
    (personal / "templates/config.json").write_text("{broken")
    with pytest.raises(KitFlowError, match="personal/templates/config.json"):
        box_update.refresh_box(destination, lambda *_: True)

    (personal / "validation.toml").write_text(rules.replace('"jsonc"', '"skip"'))
    assert box_update.refresh_box(destination, lambda *_: True) > 0
    assert configuration_issues(destination, destination) == []

    template.write_text('{"items": [,]}')
    with pytest.raises(KitFlowError, match="incoming/templates/config.json"):
        box_update.refresh_box(destination, lambda *_: True)


def test_update_is_idempotent(boxes):
    destination, _ = boxes
    assert box_update.refresh_box(destination, lambda *_: True) == 1
    assert box_update.refresh_box(destination, lambda *_: pytest.fail("No changes to review")) == 0


def test_snapshots_ignore_finder_metadata_in_all_layers(boxes):
    destination, _ = boxes
    before = box_update.snapshot(destination)
    for directory in (destination, destination / "standard", destination / "personal/templates"):
        (directory / ".DS_Store").write_bytes(b"Finder metadata")
    assert box_update.snapshot(destination) == before
    assert box_update.refresh_box(destination, lambda *_: True) == 1
    assert (destination / ".DS_Store").exists()
    assert (destination / "personal/templates/.DS_Store").exists()
    assert not (destination / "standard/.DS_Store").exists()


def test_upgrade_rejects_project_actions():
    for arguments in (["upgrade", "-c", "python"], ["upgrade", "-i"]):
        with pytest.raises(KitFlowError, match="upgrade does not accept project actions"):
            cli.run(cli.parser().parse_args(arguments))


def test_old_box_subcommand_is_removed():
    with pytest.raises(SystemExit) as error:
        cli.parser().parse_args(["box", "update"])
    assert error.value.code == 2


def test_update_and_upgrade_use_linked_personal_box(boxes, tmp_path):
    destination, _ = boxes
    personal = destination / "personal"
    vault = tmp_path / "vault"
    personal.rename(vault)
    personal.symlink_to(vault, target_is_directory=True)
    (vault / "templates/ruff.toml").write_text("line-length = 150\n")
    project = tmp_path / "project"
    project.mkdir()
    options = ["-b", str(destination), "-p", str(project), "-y"]
    assert cli.run(cli.parser().parse_args(["init", "-c", "ruff", *options])) == 0
    assert box_update.refresh_box(destination, lambda *_: True) == 1
    assert personal.is_symlink()
    (vault / "templates/ruff.toml").write_text("line-length = 160\n")
    assert cli.run(cli.parser().parse_args(["update", *options])) == 0
    assert (project / "ruff.toml").read_text() == "line-length = 160\n"


@pytest.mark.parametrize("location", ["standard", "personal", "personal/templates/broken"])
def test_broken_link_blocks_update_and_upgrade_before_writes(
    boxes, tmp_path, monkeypatch, location
):
    destination, _ = boxes
    project = tmp_path / "project"
    project.mkdir()
    options = ["-b", str(destination), "-p", str(project), "-y"]
    assert cli.run(cli.parser().parse_args(["init", "-c", "ruff", *options])) == 0
    link = destination / location
    if link.is_dir():
        link.rename(tmp_path / "disconnected")
    link.symlink_to(tmp_path / "missing")
    before = box_update.snapshot(project)
    monkeypatch.setattr(box_update, "seed_box", lambda *_: pytest.fail("Unexpected download"))
    for command in ("update", "upgrade"):
        with pytest.raises(KitFlowError, match=f"Unavailable symbolic link: .*{location}"):
            cli.run(cli.parser().parse_args([command, *options]))
    assert box_update.snapshot(project) == before


def test_linked_standard_is_readable_but_upgrade_preserves_it(boxes, tmp_path, monkeypatch):
    destination, _ = boxes
    standard = destination / "standard"
    vault = tmp_path / "shared"
    standard.rename(vault)
    standard.symlink_to(vault, target_is_directory=True)
    assert Catalog(destination).render(["ruff"])["ruff"].content
    before = box_update.snapshot(vault)
    monkeypatch.setattr(box_update, "seed_box", lambda *_: pytest.fail("Unexpected download"))
    with pytest.raises(KitFlowError, match="Cannot upgrade a linked standard box"):
        box_update.refresh_box(destination, lambda *_: True)
    assert standard.readlink() == vault
    assert box_update.snapshot(vault) == before


def test_upgrade_rolls_back_if_new_standard_breaks_personal_link(boxes):
    destination, _ = boxes
    target = destination / "standard/retired.txt"
    target.write_text("Needed by my Box")
    link = destination / "personal/templates/retired.txt"
    link.symlink_to("../../standard/retired.txt")
    before = box_update.snapshot(destination)
    with pytest.raises(KitFlowError, match="Unavailable symbolic link: .*retired.txt"):
        box_update.refresh_box(destination, lambda *_: True)
    assert box_update.snapshot(destination) == before
    assert link.read_text() == "Needed by my Box"
