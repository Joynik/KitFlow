import base64
import hashlib
import io
import json
import os
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from kitflow import cli, settings, source
from kitflow.catalog import KitFlowError


def downloads(monkeypatch, fixture: Path | None = None):
    calls = []
    fixture_root = fixture or Path(__file__).parent / "fixtures/catalog"
    commit = "a" * 40
    links = {
        hashlib.sha1(path.relative_to(fixture_root).as_posix().encode()).hexdigest(): path
        for path in fixture_root.rglob("*")
        if path.is_symlink()
    }

    def fetch(url):
        calls.append(url)
        if "/commits/" in url:
            return json.dumps({"sha": commit}).encode()
        if "/git/trees/" in url:
            assert url.endswith(f"/{commit}?recursive=1")
            return json.dumps(
                {
                    "truncated": False,
                    "tree": [
                        {
                            "path": "box/" + path.relative_to(fixture_root).as_posix(),
                            "type": "blob",
                            "mode": "120000" if path.is_symlink() else "100644",
                            "sha": hashlib.sha1(
                                path.relative_to(fixture_root).as_posix().encode()
                            ).hexdigest(),
                        }
                        for path in fixture_root.rglob("*")
                        if path.is_file() or path.is_symlink()
                    ],
                }
            ).encode()
        if "/git/blobs/" in url:
            path = links[url.rsplit("/", 1)[1]]
            return json.dumps(
                {
                    "encoding": "base64",
                    "content": base64.b64encode(os.readlink(path).encode()).decode(),
                }
            ).encode()
        prefix = f"https://api.github.com/repos/{source.DEFAULT_REPOSITORY}/contents/box/"
        assert url.startswith(prefix)
        assert url.endswith(f"?ref={commit}")
        return (fixture_root / url[len(prefix) :].split("?")[0]).read_bytes()

    monkeypatch.setattr(source, "fetch", fetch)
    return calls


def test_download_skips_finder_metadata(tmp_path, monkeypatch):
    import shutil

    fixture = tmp_path / "fixture"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", fixture)
    (fixture / ".DS_Store").write_bytes(b"Finder metadata")
    (fixture / "templates/.DS_Store").write_bytes(b"Nested Finder metadata")
    calls = downloads(monkeypatch, fixture)
    catalog, _ = source.load_box()
    assert not list(catalog.root.rglob(".DS_Store"))
    assert not any(".DS_Store" in url for url in calls)


def test_first_use_downloads_once_and_keeps_user_edits(monkeypatch):
    calls = downloads(monkeypatch)
    catalog, metadata = source.load_box()
    assert catalog.root == settings.box_path().resolve()
    assert metadata == {"kind": "user-box"}
    assert calls
    assert (catalog.root / "kitflow-box.toml").read_text().endswith("schema = 1\n")
    assert all((catalog.root / name).is_dir() for name in ("tasks", "templates"))
    assert not any("empty.md" in url for url in calls)
    assert not (catalog.root / "snapshot.json").exists()
    assert (catalog.root / "default/INSTRUCTION.md").read_text() == source.read_instructions(
        Path("box")
    )
    (catalog.root / "INSTRUCTION.md").write_text("My box instructions\n")
    (catalog.root / "templates/ruff.toml").write_text("line-length = 120\n")
    calls.clear()
    catalog, _ = source.load_box()
    assert catalog.render(["ruff"])["ruff"].content == b"line-length = 120\n"
    assert not calls
    assert (catalog.root / "INSTRUCTION.md").read_text() == "My box instructions\n"


def test_bare_command_prepares_the_box_without_touching_the_project(tmp_path, monkeypatch):
    calls = downloads(monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert cli.run(cli.parser().parse_args([])) == 0
    assert (settings.box_path() / "kitflow-box.toml").exists()
    assert (settings.box_path() / "default/INSTRUCTION.md").exists()
    assert not list(project.iterdir())
    calls.clear()
    assert cli.run(cli.parser().parse_args([])) == 0
    assert not calls


def test_incomplete_initial_download_leaves_no_partial_box(monkeypatch):
    def disconnected(_url):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(source, "fetch", disconnected)
    with pytest.raises(KitFlowError, match="Cannot prepare"):
        source.load_box()
    assert not settings.box_path().exists()
    assert not list(settings.config_directory().glob(".box-download-*"))


def test_invalid_local_box_is_not_replaced(monkeypatch):
    root = settings.box_path()
    root.mkdir(parents=True)
    (root / "kitflow-box.toml").write_text("broken = [")

    def network_forbidden(_url):
        raise AssertionError("An existing user box must not be replaced")

    monkeypatch.setattr(source, "fetch", network_forbidden)
    with pytest.raises(KitFlowError):
        source.load_box()
    assert (root / "kitflow-box.toml").read_text() == "broken = ["


def test_local_override_needs_no_bootstrap(monkeypatch):
    def network_forbidden(_url):
        raise AssertionError("A local box needs no download")

    monkeypatch.setattr(source, "fetch", network_forbidden)
    fixture = Path(__file__).parent / "fixtures/catalog"
    catalog, metadata = source.load_box(fixture)
    assert metadata == {"local": str(fixture.resolve())}
    assert "python" in catalog.components
    assert not settings.config_directory().exists()


def test_compiled_instructions_use_the_runtime_directory(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "INSTRUCTION.md").write_text("# Installed guide\n")
    monkeypatch.setattr(
        source, "__compiled__", SimpleNamespace(python_runtime_dir=str(runtime)), raising=False
    )
    assert source.read_instructions() == "# Installed guide\n"


def test_private_content_request_uses_token_and_raw_media_type(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-only-token")
    requests = []

    def open_request(request, timeout, context):
        requests.append(request)
        assert timeout == 15
        assert context.check_hostname
        return io.BytesIO(b"content")

    monkeypatch.setattr(source.urllib.request, "urlopen", open_request)
    url = source.content_url(source.DEFAULT_REPOSITORY, "a" * 40, "box/kitflow-box.toml")
    assert source.fetch(url) == b"content"
    assert requests[0].get_header("Authorization") == "Bearer test-only-token"
    assert requests[0].get_header("Accept") == "application/vnd.github.raw+json"
    assert "test-only-token" not in requests[0].full_url
    with pytest.raises(KitFlowError, match="api.github.com"):
        source.fetch("https://example.com/kitflow-box.toml")


def test_first_use_downloads_wizard_definition_from_the_same_commit(tmp_path, monkeypatch):
    import shutil

    from kitflow.wizard import Wizard

    fixture = tmp_path / "fixture"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", fixture)
    manifest = fixture / "kitflow-box.toml"
    manifest.write_text(
        manifest.read_text().replace("schema = 1", "schema = 3")
        + '\n[[steps]]\nid="languages"\nlabel="Choose a language"\ncategories=["Languages"]\n'
    )
    calls = downloads(monkeypatch, fixture)
    catalog, _ = source.load_box()
    assert Wizard(catalog, [], []).steps()[0].label == "Choose a language"
    assert all("?ref=" + "a" * 40 in url for url in calls if "/contents/" in url)


@pytest.mark.parametrize("truncated", [True, False])
def test_invalid_download_keeps_initial_box_absent(monkeypatch, truncated):
    downloads(monkeypatch)
    original = source.fetch

    def invalid_tree(url):
        if "/git/trees/" in url:
            return json.dumps(
                {
                    "truncated": truncated,
                    "tree": [{"path": "box/tasks/example.sh", "type": "commit", "mode": "160000"}],
                }
            ).encode()
        return original(url)

    monkeypatch.setattr(source, "fetch", invalid_tree)
    with pytest.raises(KitFlowError, match="incomplete|Unsupported"):
        source.load_box()
    assert not settings.box_path().exists()
    assert not list(settings.config_directory().glob(".box-download-*"))


def test_initial_download_includes_hidden_binary_directory_templates_and_link_text(
    tmp_path, monkeypatch
):
    import shutil

    fixture = tmp_path / "fixture"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", fixture)
    (fixture / "templates/editor/.nested").mkdir(parents=True)
    (fixture / "templates/editor/.nested/file.pdf").write_bytes(b"%PDF\x00\xff")
    (fixture / "templates/editor/skill").symlink_to("../../personal-skill")
    with (fixture / "kitflow-box.toml").open("a") as stream:
        stream.write('[[files]]\nid="editor"\npath=".vscode"\ntemplate="templates/editor"\n')
    calls = downloads(monkeypatch, fixture)
    catalog, _ = source.load_box()
    artifacts = catalog.render([])
    assert artifacts["editor/.nested/file.pdf"].content == b"%PDF\x00\xff"
    assert artifacts["editor/skill"].content == "../../personal-skill"
    assert artifacts["editor/skill"].kind == "symlink"
    assert any("/git/blobs/" in url for url in calls)
    assert not any("/contents/box/templates/editor/skill" in url for url in calls)
