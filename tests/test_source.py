import io
import json
import urllib.error
from pathlib import Path

import pytest

from kitflow import settings, source
from kitflow.catalog import KitFlowError


def downloads(monkeypatch):
    calls = []
    fixture = Path(__file__).parent / "fixtures/catalog"
    commit = "a" * 40

    def fetch(url):
        calls.append(url)
        if "/commits/" in url:
            return json.dumps({"sha": commit}).encode()
        prefix = f"https://api.github.com/repos/{source.DEFAULT_REPOSITORY}/contents/box/"
        assert url.startswith(prefix)
        assert url.endswith(f"?ref={commit}")
        return (fixture / url[len(prefix) :].split("?")[0]).read_bytes()

    monkeypatch.setattr(source, "fetch", fetch)
    return calls


def test_first_use_downloads_once_and_keeps_user_edits(monkeypatch):
    calls = downloads(monkeypatch)
    catalog, metadata = source.load_box()
    assert catalog.root == settings.box_path().resolve()
    assert metadata == {"kind": "user-box"}
    assert calls
    assert not any("empty.md" in url for url in calls)
    assert not (catalog.root / "snapshot.json").exists()
    (catalog.root / "templates/ruff.toml").write_text("line-length = 120\n")
    calls.clear()
    catalog, _ = source.load_box()
    assert catalog.render(["ruff"])["ruff"].content == b"line-length = 120\n"
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
