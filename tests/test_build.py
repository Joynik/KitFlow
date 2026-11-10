"""Reject unsupported hosts before starting native compilation."""

import importlib.util
from pathlib import Path

import pytest


def test_macos_intel_build_is_rejected_before_compilation(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "build_standalone", Path(__file__).parents[1] / "scripts/build_standalone.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(module.sys, "argv", ["build_standalone.py"])

    def compilation_forbidden(*_args, **_kwargs):
        raise AssertionError("An unsupported host must not start compilation")

    monkeypatch.setattr(module.subprocess, "run", compilation_forbidden)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    assert "Unsupported standalone target: macos-x86_64" in capsys.readouterr().err
