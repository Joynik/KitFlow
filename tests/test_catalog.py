from pathlib import Path

import pytest

from kitflow.catalog import Catalog, KitFlowError, safe_path


def test_dependencies_and_composed_tasks(tmp_path):
    (tmp_path / "python.sh").write_text("ruff check .\n")
    (tmp_path / "django.sh").write_text("python manage.py check\n")
    (tmp_path / "kitflow-box.toml").write_text("""schema = 1
[[components]]
id = "python"
label = "Python"
category = "Languages"
[[components]]
id = "django"
label = "Django"
category = "Frameworks"
requires = ["python"]
[[tasks]]
name = "lint"
when = ["python"]
template = "python.sh"
[[tasks]]
name = "lint"
when = ["django"]
template = "django.sh"
""")
    catalog = Catalog(tmp_path)
    assert catalog.resolve(["django"]) == ["python", "django"]
    content = catalog.render(["django"])["task.lint"].content.decode()
    assert content.index("ruff") < content.index("manage.py")
    assert "manage.py" not in catalog.render(["python"])["task.lint"].content.decode()


@pytest.mark.parametrize("name", ["../outside", "/tmp/outside", ".git/config", "kitflow.toml"])
def test_unsafe_paths_rejected(tmp_path, name):
    with pytest.raises(KitFlowError):
        safe_path(tmp_path, name)


def test_symlink_rejected(tmp_path):
    (tmp_path / "link").symlink_to(Path("/tmp"), target_is_directory=True)
    with pytest.raises(KitFlowError):
        safe_path(tmp_path, "link/config")


@pytest.mark.parametrize(
    "extra",
    [
        '[[files]]\nid="same"\npath="a"\ntemplate="t"\n[[files]]\nid="same"\npath="b"\ntemplate="t"',
        '[[files]]\nid="file"\npath="x"\ntemplate="t"\nmode="invalid"',
        '[[tasks]]\nname="lint"\ntemplate="t"\nwhen="python"',
        '[[files]]\nid="project"\npath="PROJECT.md"\nempty=true',
        '[[files]]\nid="project"\npath="PROJECT.md"\nempty=true\nmode="once"\ntemplate="t"',
    ],
)
def test_invalid_catalog_rejected(tmp_path, extra):
    (tmp_path / "t").write_text("echo test")
    (tmp_path / "kitflow-box.toml").write_text(
        """schema = 1
[[components]]
id = "python"
label = "Python"
category = "Languages"
"""
        + extra
    )
    with pytest.raises(KitFlowError):
        Catalog(tmp_path)


def test_empty_document_does_not_need_a_template(tmp_path):
    from kitflow.engine import apply, load_config, plan

    (tmp_path / "kitflow-box.toml").write_text("""schema = 1
[[components]]
id = "base"
label = "Base"
category = "General"
[[files]]
id = "project"
path = "PROJECT.md"
empty = true
mode = "once"
""")
    catalog = Catalog(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    apply(plan(project, catalog, ["base"], load_config(project)), {})
    assert (project / "PROJECT.md").read_bytes() == b""
    (project / "PROJECT.md").write_text("User notes")
    assert not plan(project, catalog, ["base"], load_config(project)).changes
