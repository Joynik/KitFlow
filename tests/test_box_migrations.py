import shutil
import subprocess
from pathlib import Path

import pytest

from kitflow import box_migrations, cli, mise
from kitflow.catalog import Catalog, KitFlowError
from kitflow.engine import load_config

BOX = Path(__file__).resolve().parents[1] / "box"


def test_update_leaves_legacy_translation_keys_user_owned(tmp_path):
    (tmp_path / "kitflow.toml").write_text("schema=1\n[selection]\ncomponents=[]\n")
    config = tmp_path / "mise.toml"
    config.write_text('[vars]\ni18n_source_language = "uk"\n')
    args = cli.parser().parse_args(["update", "-b", str(BOX), "-p", str(tmp_path), "-y"])
    assert cli.run(args) == 0
    assert mise.parse(config.read_text())["vars"]["i18n_source_language"] == "uk"
    project = load_config(tmp_path)
    assert project["box_version"] == Catalog(BOX).version
    assert "migrated_box_version" not in project


def test_future_migration_is_required_even_if_box_already_applied(tmp_path, monkeypatch):
    box = tmp_path / "box"
    shutil.copytree(BOX, box)
    (box / ".version").write_text("5\n")
    (box / ".migration").write_text("2\n")
    project = tmp_path / "project"
    project.mkdir()
    config = project / "kitflow.toml"
    original = "schema=1\nbox_version=5\nmigrated_box_version=1\n[selection]\ncomponents=[]\n"
    config.write_text(original)
    args = cli.parser().parse_args(["update", "-b", str(box), "-p", str(project), "-y"])
    with pytest.raises(KitFlowError, match="upgrade KitFlow first"):
        cli.run(args)
    assert config.read_text() == original

    executed = []
    monkeypatch.setitem(box_migrations.MIGRATIONS, 2, lambda _plan, _text: executed.append(2))
    assert cli.run(args) == 0
    assert executed == [2]
    assert load_config(project)["migrated_box_version"] == 2


def test_box_counter_counts_content_commits_and_ignores_its_own_commit(tmp_path):
    script = BOX.parent / "scripts" / "update_box_version.sh"
    remote, project = tmp_path / "remote.git", tmp_path / "repo"
    project.mkdir()

    def run(*args, check=True):
        return subprocess.run(args, cwd=project, text=True, capture_output=True, check=check)

    run("git", "init", "--bare", str(remote))
    run("git", "init", "-b", "main")
    run("git", "config", "user.name", "Box test")
    run("git", "config", "user.email", "test@example.com")
    run("git", "remote", "add", "origin", str(remote))
    box = project / "box"
    box.mkdir()
    version = box / ".version"
    version.write_text("1\n")
    template = box / "template.txt"
    for value in ("initial", "second", "third"):
        template.write_text(value)
        run("git", "add", "box")
        run("git", "commit", "-m", value)
    run("git", "push", "origin", "main")
    assert run("bash", str(script), "check", check=False).returncode == 1
    run("bash", str(script))
    assert version.read_text() == "3\n"
    run("bash", str(script), "check")
    revision = run("git", "rev-parse", "HEAD").stdout
    run("bash", str(script))
    assert run("git", "rev-parse", "HEAD").stdout == revision


def test_cancel_update_after_migration_keeps_applied_revision_pending(tmp_path, monkeypatch):
    box = tmp_path / "box"
    shutil.copytree(BOX, box)
    (box / ".migration").write_text("2\n")
    monkeypatch.setitem(box_migrations.MIGRATIONS, 2, lambda _plan, _text: None)
    config = tmp_path / "kitflow.toml"
    config.write_text("schema=1\n[selection]\ncomponents=[]\n")
    original = config.read_bytes()
    args = cli.parser().parse_args(["update", "-b", str(box), "-p", str(tmp_path)])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "choose_action", lambda *_: "cancel")
    assert cli.run(args) == 0
    assert config.read_bytes() == original

    answers = iter(["apply", "exit"])
    monkeypatch.setattr(cli, "choose_action", lambda *_: next(answers))
    assert cli.run(args) == 0
    migrated = load_config(tmp_path)
    assert migrated["migrated_box_version"] == 2
    assert "box_version" not in migrated

    def exit_update(title, *_):
        assert title == "What would you like to do?"
        return "exit"

    monkeypatch.setattr(cli, "choose_action", exit_update)
    assert cli.run(args) == 0
