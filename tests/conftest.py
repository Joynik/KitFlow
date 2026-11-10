import pytest


@pytest.fixture(autouse=True)
def isolate_user_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
