import json
import tomllib
from pathlib import Path

import pytest

from kitflow.catalog import Catalog
from kitflow.engine import apply, load_config, plan, preview_files

BOX = Path(__file__).resolve().parents[1] / "box"


def test_manifest_additions_are_opt_in_and_preserve_existing_settings(tmp_path):
    catalog = Catalog(BOX)
    initial = plan(tmp_path, catalog, ["python", "typescript", "rust"], {})
    apply(initial, {})
    pyproject = tmp_path / "pyproject.toml"
    package = tmp_path / "package.json"
    cargo = tmp_path / "Cargo.toml"
    assert "devDependencies" not in json.loads(package.read_text())
    assert "dependency-groups" not in tomllib.loads(pyproject.read_text())
    assert "metadata" not in tomllib.loads(cargo.read_text())["package"]

    pyproject.write_text(
        pyproject.read_text()
        + '\n# Keep this comment.\n[dependency-groups]\ndev = [{include-group = "quality"}, "pytest"]\nquality = ["Vulture==2.15"]\n'
        + "\n[tool.vulture]\nmin_confidence = 90\n"
    )
    package.write_text('{"name":"custom","scripts":{"test":"node test.js"}}\n')
    cargo.write_text('[workspace]\nmembers = ["member"]\n')
    selected = ["typescript", "knip", "vulture", "deptry", "cargo-machete"]
    document = load_config(tmp_path)
    update = plan(tmp_path, catalog, selected, document)
    assert {"pyproject.toml", "package.json", "Cargo.toml", "knip.json"} <= preview_files(
        update
    ).keys()
    apply(update, document["source"])

    assert "# Keep this comment." in pyproject.read_text()
    python = tomllib.loads(pyproject.read_text())
    assert python["dependency-groups"]["dev"] == [
        {"include-group": "quality"},
        "pytest",
        "deptry>=0.25.1",
    ]
    assert python["tool"]["vulture"]["min_confidence"] == 90
    js = json.loads(package.read_text())
    assert js["scripts"] == {"test": "node test.js"}
    assert "knip" in js["devDependencies"]
    rust = tomllib.loads(cargo.read_text())
    assert rust == {
        "workspace": {"members": ["member"], "metadata": {"cargo-machete": {"ignored": []}}}
    }
    tasks = tomllib.loads((tmp_path / "mise.toml").read_text())["tasks"]
    assert {"check-unused", "check-deps", "install-cargo-machete"} <= tasks.keys()
    assert not preview_files(plan(tmp_path, catalog, selected, load_config(tmp_path)))
    assert "package.json" not in preview_files(
        plan(tmp_path, catalog, ["javascript"], load_config(tmp_path))
    )


def test_manifest_paths_follow_project_settings_and_platform_defaults(tmp_path):
    catalog = Catalog(BOX)
    (tmp_path / "mise.toml").write_text('[vars]\njavascript_directory = "frontend"\n')
    result = plan(tmp_path, catalog, ["tauri", "knip"], {})
    outputs = preview_files(result)
    assert {"frontend/package.json", "frontend/knip.json", "src-tauri/Cargo.toml"} <= outputs.keys()
    assert "Cargo.toml" not in outputs
    assert "package.json" not in outputs

    result = plan(tmp_path, catalog, ["vscode-extension", "knip"], {})
    raw = preview_files(result)["package.json"][1]
    assert isinstance(raw, bytes)
    package = json.loads(raw)
    assert "contributes" in package
    assert "knip" in package["devDependencies"]


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (".knip.jsonc", "{}\n"),
        ("package.json", '{"knip":{"entry":"custom.js"}}\n'),
    ],
)
def test_default_config_does_not_shadow_an_existing_alternative(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    result = plan(tmp_path, Catalog(BOX), ["knip"], {})
    assert "knip.json" not in preview_files(result)
    assert "package.json" in preview_files(result)
