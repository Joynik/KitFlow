from pathlib import Path

from kitflow.catalog import Catalog
from kitflow.engine import apply, load_config, plan


def test_example_box_builds_basic_python_project(tmp_path):
    root = Path(__file__).parents[1] / "box"
    catalog = Catalog(root)
    selected = ["python", "ruff", "ty", "rumdl", "agents"]
    apply(plan(tmp_path, catalog, selected, load_config(tmp_path)), {"local": str(root)})
    assert (tmp_path / "PROJECT.md").read_bytes() == b""
    assert (tmp_path / "README.md").read_bytes() == b""
    assert (tmp_path / "ruff.toml").exists()
    assert not plan(tmp_path, catalog, selected, load_config(tmp_path)).changes


def test_example_box_has_no_removed_tool_templates():
    root = Path(__file__).parents[1] / "box"
    assert not (root / "templates/skills").exists()
    for path in root.rglob("*"):
        if path.is_file():
            text = path.read_text().lower()
            assert "beads" not in text, path
            assert "graphify" not in text, path
