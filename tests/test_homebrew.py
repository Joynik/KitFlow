"""Validate release inputs before writing public installation metadata."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "update_homebrew", Path(__file__).parents[1] / "scripts/update_homebrew.py"
)
assert spec
assert spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def release_data():
    names = [f"kitflow-0.1.0-{platform}.tar.gz" for platform in module.PLATFORMS]
    root = "https://github.com/Joynik/KitFlow"
    release = {
        "tag_name": "0.1.0",
        "html_url": f"{root}/releases/tag/0.1.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"{root}/releases/download/0.1.0/{name}",
                "state": "uploaded",
                "digest": "sha256:" + "a" * 64,
            }
            for name in names
        ],
    }
    checksums = "\n".join("a" * 64 + f"  ./{name}" for name in names)
    return release, checksums


def test_formula_preserves_standalone_runtime_and_platform_checksums():
    release, checksums = release_data()
    result = module.formula(release, checksums)
    for asset in release["assets"]:
        assert asset["browser_download_url"] in result
    assert 'libexec.install Dir["*"]' in result
    assert 'bin.install_symlink libexec/"kitflow"' in result


@pytest.mark.parametrize("invalid", ["draft", "missing", "digest", "repository"])
def test_formula_rejects_incomplete_or_untrusted_release(invalid):
    release, checksums = release_data()
    if invalid == "draft":
        release["draft"] = True
    elif invalid == "missing":
        release["assets"].pop()
    elif invalid == "digest":
        release["assets"][0]["digest"] = "sha256:" + "b" * 64
    else:
        release["html_url"] = "https://example.com/releases/tag/0.1.0"
    with pytest.raises((ValueError, KeyError)):
        module.formula(release, checksums)
