import tomllib

import pytest

from kitflow.catalog import Artifact, Catalog, KitFlowError
from kitflow.engine import apply, load_config, plan


class FakeCatalog(Catalog):
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.version = 0

    def resolve(self, selected, *, check_conflicts=True):
        return selected

    def render(self, selected, *, check_conflicts=True):
        return self.artifacts if selected else {}


def make_plan(root, artifacts, selected=None):
    return plan(
        root,
        FakeCatalog(artifacts),
        ["python"] if selected is None else selected,
        load_config(root),
    )


def test_file_lifecycle_manual_config_edit_and_once(tmp_path):
    artifacts = {
        "ruff": Artifact("ruff", "ruff.toml", b"line-length = 100\n"),
        "project": Artifact("project", "PROJECT.md", b"", True),
    }
    apply(make_plan(tmp_path, artifacts), {})
    (tmp_path / "PROJECT.md").write_text("My project")
    assert not make_plan(tmp_path, artifacts).changes
    config = (tmp_path / "kitflow.toml").read_text().replace('["python"]', "[]")
    (tmp_path / "kitflow.toml").write_text(config)
    result = plan(tmp_path, FakeCatalog({}), [], load_config(tmp_path))
    apply(result, {})
    assert not (tmp_path / "ruff.toml").exists()
    assert (tmp_path / "PROJECT.md").read_text() == "My project"


@pytest.mark.parametrize("path", ["ruff.toml", "nested/ruff.toml"])
def test_conflicts_and_persistent_exclusion(tmp_path, path):
    (tmp_path / path).parent.mkdir(exist_ok=True)
    (tmp_path / path).write_text("custom")
    artifacts = {"ruff": Artifact("ruff", path, b"standard")}
    result = make_plan(tmp_path, artifacts)
    assert result.changes[0].conflict
    with pytest.raises(KitFlowError, match="Resolve conflicts"):
        apply(result, {})
    assert not (tmp_path / "kitflow.toml").exists()
    result.changes[0].decision = "keep"
    apply(result, {})
    assert not make_plan(tmp_path, artifacts).changes
    assert (tmp_path / path).read_text() == "custom"
    assert load_config(tmp_path)["selection"]["excluded"] == ["ruff.toml"]


def test_local_modification_update_and_delete_protected(tmp_path):
    artifacts = {"ruff": Artifact("ruff", "ruff.toml", b"standard")}
    apply(make_plan(tmp_path, artifacts), {})
    (tmp_path / "ruff.toml").write_text("custom")
    assert make_plan(tmp_path, artifacts).changes[0].conflict
    assert make_plan(tmp_path, {}, []).changes[0].conflict


def test_mise_composition_env_and_detachment(tmp_path):
    original = (
        '# Custom settings\n[env]\nUSER_VALUE = "keep"\n\n[tasks.custom]\nrun = "echo user"\n'
    )
    (tmp_path / "mise.toml").write_text(original)
    artifacts = {
        "task.lint": Artifact(
            "task.lint",
            "mise.toml",
            b'[tasks.lint]\nrun = "ruff check ."\n',
            kind="task",
            key="lint",
        ),
        "env.PYTHONPATH": Artifact(
            "env.PYTHONPATH", "mise.toml", b'PYTHONPATH = "src"\n', kind="env", key="PYTHONPATH"
        ),
    }
    apply(make_plan(tmp_path, artifacts), {})
    mise = (tmp_path / "mise.toml").read_text()
    data = tomllib.loads(mise)
    assert data["env"] == {"USER_VALUE": "keep", "PYTHONPATH": "src"}
    assert data["tasks"]["custom"]["run"] == "echo user"
    assert not make_plan(tmp_path, artifacts).changes
    detached = mise.replace("# kitflow:begin task.lint\n", "").replace(
        "# kitflow:end task.lint\n", ""
    )
    (tmp_path / "mise.toml").write_text(detached)
    result = make_plan(tmp_path, artifacts)
    assert result.changes[0].operation == "detach"
    apply(result, {})
    assert (tmp_path / "mise.toml").read_text() == detached
    apply(make_plan(tmp_path, {}, []), {})
    data = tomllib.loads((tmp_path / "mise.toml").read_text())
    assert "PYTHONPATH" not in data["env"]
    assert "lint" in data["tasks"]


def test_incomplete_marker_aborts_without_writes(tmp_path):
    (tmp_path / "mise.toml").write_text('# kitflow:begin task.lint\n[tasks.lint]\nrun="x"\n')
    artifacts = {"task.lint": Artifact("task.lint", "mise.toml", b"", kind="task", key="lint")}
    with pytest.raises(KitFlowError, match="Unpaired"):
        make_plan(tmp_path, artifacts)


def test_concurrent_edit_aborts(tmp_path):
    artifacts = {"ruff": Artifact("ruff", "ruff.toml", b"standard")}
    result = make_plan(tmp_path, artifacts)
    (tmp_path / "ruff.toml").write_text("new user edit")
    with pytest.raises(KitFlowError, match="changed after planning"):
        apply(result, {})
    assert (tmp_path / "ruff.toml").read_text() == "new user edit"


def test_write_failure_rolls_back(tmp_path, monkeypatch):
    from kitflow import engine

    (tmp_path / "one.txt").write_text("old")
    artifacts = {
        "one": Artifact("one", "one.txt", b"new"),
        "two": Artifact("two", "sub/two.txt", b"new"),
    }
    result = make_plan(tmp_path, artifacts)
    for change in result.changes:
        change.decision = "apply"
    original = engine.atomic_write

    def fail_second(path, content, mode=None):
        if path.name == "two.txt":
            raise OSError("Disk failure")
        original(path, content, mode)

    monkeypatch.setattr(engine, "atomic_write", fail_second)
    with pytest.raises(OSError, match="Disk failure"):
        apply(result, {})
    assert (tmp_path / "one.txt").read_text() == "old"
    assert not (tmp_path / "sub").exists()
    assert not (tmp_path / "kitflow.toml").exists()


def test_mise_modified_blocks_conflict_and_can_be_restored(tmp_path):
    artifact = Artifact(
        "task.lint", "mise.toml", b'[tasks.lint]\nrun="standard"\n', kind="task", key="lint"
    )
    artifacts = {artifact.id: artifact}
    apply(make_plan(tmp_path, artifacts), {})
    path = tmp_path / "mise.toml"
    path.write_text(path.read_text().replace('run="standard"', 'run="custom"'))
    result = make_plan(tmp_path, artifacts)
    assert result.changes[0].conflict
    result.changes[0].decision = "keep"
    apply(result, {})
    document = load_config(tmp_path)
    assert "task.lint" in document["selection"]["excluded"]
    document["selection"]["excluded"] = []
    result = plan(tmp_path, FakeCatalog(artifacts), ["python"], document)
    assert result.changes[0].conflict
    result.changes[0].decision = "apply"
    apply(result, {})
    assert 'run="standard"' in path.read_text()


def test_plan_protects_existing_symlink_and_config_comments_survive(tmp_path):
    artifacts = {"ruff": Artifact("ruff", "ruff.toml", b"standard")}
    apply(make_plan(tmp_path, artifacts), {})
    config = tmp_path / "kitflow.toml"
    config.write_text("# My selection\n" + config.read_text())
    apply(make_plan(tmp_path, artifacts), {})
    assert config.read_text().startswith("# My selection\n")
    (tmp_path / "ruff.toml").unlink()
    (tmp_path / "ruff.toml").symlink_to("/tmp")
    result = make_plan(tmp_path, artifacts)
    assert result.changes[0].conflict
    with pytest.raises(KitFlowError, match="Resolve conflicts"):
        apply(result, {})
    assert (tmp_path / "ruff.toml").is_symlink()


def test_concurrent_kitflow_application_is_rejected(tmp_path):
    import fcntl
    import os

    result = make_plan(tmp_path, {"a": Artifact("a", "a.txt", b"new")})
    descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with pytest.raises(KitFlowError, match="Another KitFlow"):
            apply(result, {})
    finally:
        os.close(descriptor)
    assert not (tmp_path / "a.txt").exists()


@pytest.mark.parametrize("original", ['[env] # My settings\nLOCAL = "user"\n', "[env]"])
def test_env_header_comment_and_missing_final_newline(tmp_path, original):
    (tmp_path / "mise.toml").write_text(original)
    artifact = Artifact("env.NAME", "mise.toml", b'NAME = "value"\n', kind="env", key="NAME")
    apply(make_plan(tmp_path, {artifact.id: artifact}), {})
    assert not make_plan(tmp_path, {artifact.id: artifact}).changes
    apply(make_plan(tmp_path, {}, []), {})
    assert "NAME" not in tomllib.loads((tmp_path / "mise.toml").read_text())["env"]


@pytest.mark.parametrize("selected", [["python"], []])
@pytest.mark.parametrize("modified", [False, True])
def test_managed_file_becomes_creation_only_before_update_or_removal(tmp_path, selected, modified):
    box = tmp_path / "box"
    box.mkdir()
    manifest = box / "kitflow-box.toml"
    manifest.write_text(
        'schema=4\n[[components]]\nid="python"\nlabel="Python"\ncategory="Languages"\n'
        '[[files]]\nid="pyproject"\npath="pyproject.toml"\ntemplate="project.toml"\n'
        'when=["python"]\nmode="managed"\n'
    )
    (box / "project.toml").write_text('[project]\nname="example"\n')
    project = tmp_path / "project"
    project.mkdir()
    apply(plan(project, Catalog(box), ["python"], load_config(project)), {})
    pyproject = project / "pyproject.toml"
    if modified:
        pyproject.write_text('[project]\nname="personal"\nversion="1.2.3"\n')
    original = pyproject.read_bytes()
    venv = project / ".venv" / "sentinel"
    venv.parent.mkdir()
    venv.write_bytes(b"user environment\x00")
    manifest.write_text(manifest.read_text().replace('mode="managed"', 'mode="once"'))
    (box / "project.toml").write_text('[project]\nname="changed"\n')
    result = plan(project, Catalog(box), selected, load_config(project))
    assert not any(c.artifact.id == "pyproject" for c in result.changes)
    apply(result, {})
    assert pyproject.read_bytes() == original
    assert venv.read_bytes() == b"user environment\x00"
    assert load_config(project)["state"]["artifacts"]["pyproject"]["once"] is True
    once_manifest = manifest.read_text()
    manifest.write_text(once_manifest.split("[[files]]")[0])
    apply(plan(project, Catalog(box), [], load_config(project)), {})
    assert pyproject.read_bytes() == original
    pyproject.unlink()
    manifest.write_text(once_manifest)
    assert not any(
        c.artifact.id == "pyproject"
        for c in plan(project, Catalog(box), ["python"], load_config(project)).changes
    )


def test_exclusion_uses_internal_path_for_files_with_the_same_name(tmp_path):
    (tmp_path / "one").mkdir()
    local = tmp_path / "one/settings.toml"
    local.write_text("custom")
    artifacts = {
        "one": Artifact("one", "one/settings.toml", b"standard"),
        "two": Artifact("two", "two/settings.toml", b"standard"),
    }
    result = make_plan(tmp_path, artifacts)
    assert result.changes[0].conflict
    result.changes[0].decision = "keep"
    apply(result, {})
    document = load_config(tmp_path)
    assert document["selection"]["excluded"] == ["settings.toml"]
    assert document["state"]["excluded_paths"] == ["one/settings.toml"]

    artifacts["two"] = Artifact("two", "two/settings.toml", b"updated")
    result = make_plan(tmp_path, artifacts)
    assert [change.artifact.path for change in result.changes] == ["two/settings.toml"]
    apply(result, {})
    assert local.read_text() == "custom"
    assert (tmp_path / "two/settings.toml").read_text() == "updated"
