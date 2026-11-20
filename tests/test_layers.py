import shutil
from pathlib import Path

import pytest

from kitflow.catalog import Catalog, KitFlowError
from kitflow.check import configuration_issues


@pytest.fixture
def layered(tmp_path):
    root = tmp_path / "box"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", root / "standard")
    (root / "personal").mkdir()
    (root / "personal/kitflow-box.toml").write_text("schema = 1\n")
    return root


def test_user_records_replace_whole_entries_and_add_components(layered):
    (layered / "personal/kitflow-box.toml").write_text("""schema = 1
[[components]]
id = "ruff"
label = "My Ruff"
category = "Checks"
[[components]]
id = "extra"
label = "Extra"
category = "Checks"
""")
    catalog = Catalog(layered)
    assert catalog.components["ruff"].label == "My Ruff"
    assert catalog.components["ruff"].requires == ()
    assert "extra" in catalog.components
    assert "python" in catalog.components


def test_templates_merge_hidden_binary_and_links_without_traversal(layered):
    for base in (layered / "personal", layered / "standard"):
        (base / "templates/editor/nested").mkdir(parents=True)
    (layered / "standard/templates/editor/.hidden").write_bytes(b"\x00\xff")
    (layered / "standard/templates/editor/nested/shared").write_text("standard")
    (layered / "personal/templates/editor/nested/shared").write_text("user")
    (layered / "personal/templates/editor/link").symlink_to("../missing")
    with (layered / "personal/kitflow-box.toml").open("a") as stream:
        stream.write("""[[files]]
id = "editor"
path = ".vscode"
template = "templates/editor"
""")
    artifacts = Catalog(layered).render([])
    assert artifacts["editor/.hidden"].content == b"\x00\xff"
    assert artifacts["editor/nested/shared"].content == b"user"
    assert artifacts["editor/link"].content == "../missing"
    assert artifacts["editor/link"].kind == "symlink"


def test_task_fragment_ids_replace_one_fragment_only(layered):
    with (layered / "standard/kitflow-box.toml").open("a") as stream:
        stream.write("""[[tasks]]
id = "additional"
name = "lint"
template = "tasks/additional.sh"
when = ["ruff"]
""")
    (layered / "standard/tasks").mkdir()
    (layered / "standard/tasks/additional.sh").write_text("echo additional")
    (layered / "personal/tasks").mkdir()
    (layered / "personal/tasks/custom.sh").write_text("echo custom")
    with (layered / "personal/kitflow-box.toml").open("a") as stream:
        stream.write("""[[tasks]]
id = "ruff"
name = "lint"
template = "tasks/custom.sh"
when = ["ruff"]
""")
    content = Catalog(layered).render(["ruff"])["task.lint"].content
    assert isinstance(content, bytes)
    assert b"echo custom" in content
    assert b"echo additional" in content
    assert b"ruff check" not in content


def test_steps_override_and_disable(layered):
    for base, label in [(layered / "standard", "Standard"), (layered / "personal", "User")]:
        path = base / "kitflow-box.toml"
        path.write_text(
            path.read_text()
            + f'\n[[steps]]\nid="setup"\nlabel="{label}"\ncategories=["Languages"]\n'
        )
    assert Catalog(layered).data["steps"][0]["label"] == "User"
    with (layered / "personal/kitflow-box.toml").open("a") as stream:
        stream.write('[disabled]\nsteps=["setup"]\nfiles=["ruff"]\ntasks=["ruff"]\n')
    catalog = Catalog(layered)
    assert catalog.data["steps"] == []
    assert "ruff" not in catalog.render(["ruff"])


@pytest.mark.parametrize(
    "text",
    [
        '[disabled]\nfiles=["missing"]',
        '[disabled]\ntasks="bad"',
        "[disabled]\nunknown=[]",
        '[[tasks]]\nid="same"\nname="a"\ntemplate="a"\n[[tasks]]\nid="same"\nname="b"\ntemplate="b"',
    ],
)
def test_invalid_overrides_rejected(layered, text):
    with (layered / "personal/kitflow-box.toml").open("a") as stream:
        stream.write(text)
    with pytest.raises(KitFlowError):
        Catalog(layered)


def test_check_reports_unknown_fields_even_in_replaced_standard_entries(layered, tmp_path):
    manifest = layered / "standard/kitflow-box.toml"
    manifest.write_text(
        manifest.read_text().replace('label = "Python"', 'label = "Python"\nunknown = true')
    )
    assert any("Unknown fields" in error for _, error in configuration_issues(layered, tmp_path))


def test_removing_file_override_restores_standard(layered):
    (layered / "personal/templates").mkdir()
    override = layered / "personal/templates/ruff.toml"
    override.write_bytes(b"")
    assert Catalog(layered).render(["ruff"])["ruff"].content == b""
    override.unlink()
    assert Catalog(layered).render(["ruff"])["ruff"].content


def test_check_validates_standard_templates_even_when_overridden(layered, tmp_path):
    (layered / "standard/templates/ruff.toml").write_text("broken = [")
    (layered / "personal/templates").mkdir()
    (layered / "personal/templates/ruff.toml").write_text("line-length = 100")
    assert any(
        path == layered / "standard/templates/ruff.toml"
        for path, _ in configuration_issues(layered, tmp_path)
    )


def test_environment_override_uses_id_not_variable_name(layered):
    with (layered / "personal/kitflow-box.toml").open("a") as stream:
        stream.write("""[[env]]
id = "PYTHONUNBUFFERED"
name = "CUSTOM"
value = "yes"
""")
    artifacts = Catalog(layered).render(["python"])
    assert "env.PYTHONUNBUFFERED" not in artifacts
    assert artifacts["env.CUSTOM"].content == b'CUSTOM = "yes"\n'


def test_user_directory_replaces_standard_file(layered):
    (layered / "standard/templates/editor").write_text("standard file")
    (layered / "personal/templates/editor").mkdir(parents=True)
    (layered / "personal/templates/editor/user.txt").write_text("user")
    with (layered / "personal/kitflow-box.toml").open("a") as stream:
        stream.write('[[files]]\nid="editor"\npath=".editor"\ntemplate="templates/editor"\n')
    assert Catalog(layered).render([])["editor/user.txt"].content == b"user"
