import shutil
from pathlib import Path

import pytest

from kitflow.catalog import Catalog, KitFlowError
from kitflow.profiles import load_profiles


@pytest.fixture
def profile_box(tmp_path):
    box = tmp_path / "box"
    shutil.copytree(Path(__file__).parent / "fixtures/catalog", box)
    (box / "profiles").mkdir()
    return box


def test_profile_resolves_dependencies_without_changing_files(profile_box):
    path = profile_box / "profiles/django.toml"
    path.write_text('name = "Django"\ncomponents = ["django", "ruff"]\n')
    profile = load_profiles(Catalog(profile_box))["django"]
    assert profile.name == "Django"
    assert profile.description == ""
    assert profile.components == ["python", "django", "ruff"]
    assert path.read_text() == 'name = "Django"\ncomponents = ["django", "ruff"]\n'


@pytest.mark.parametrize(
    ("filename", "text", "message"),
    [
        ("Broken.toml", 'name = "X"\ncomponents = []', "lowercase"),
        ("bad.toml", 'name = "X"\ncomponents = [', "Invalid value"),
        ("bad.toml", 'name = "X"\ncomponents = "ruff"', "array"),
        ("bad.toml", 'name = "X"\ncomponents = ["unknown"]', "Unknown component"),
        ("bad.toml", 'name = "X"\ncomponents = ["ruff", "ruff"]', "duplicate"),
        ("bad.toml", 'name = "X"\ncomponents = []\nextra = true', "Unknown profile"),
        ("bad.toml", 'name = " "\ncomponents = []', "nonempty"),
        ("bad.toml", 'name = "X"\ncomponents = []\ndescription = 1', "description"),
    ],
)
def test_invalid_profiles_report_the_file(profile_box, filename, text, message):
    (profile_box / "profiles" / filename).write_text(text)
    with pytest.raises(KitFlowError, match=message) as error:
        load_profiles(Catalog(profile_box))
    assert filename in str(error.value)


def test_profile_conflicts_are_rejected(profile_box):
    manifest = profile_box / "kitflow-box.toml"
    manifest.write_text(
        manifest.read_text().replace('id = "django"', 'id = "django"\nconflicts = ["ruff"]', 1)
    )
    (profile_box / "profiles/django.toml").write_text(
        'name = "Django"\ncomponents = ["django", "ruff"]'
    )
    with pytest.raises(KitFlowError, match="conflicts"):
        load_profiles(Catalog(profile_box))


def test_profiles_are_optional_and_config_links_are_rejected(profile_box):
    shutil.rmtree(profile_box / "profiles")
    assert load_profiles(Catalog(profile_box)) == {}
    (profile_box / "profiles").symlink_to("templates", target_is_directory=True)
    with pytest.raises(KitFlowError, match="Symbolic links"):
        load_profiles(Catalog(profile_box))


def invoke_profile(box, project, *arguments):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "kitflow", *arguments, "-b", str(box), "-p", str(project)],
        capture_output=True,
        text=True,
    )


def test_cli_profile_snapshot_reapply_and_manual_selection(profile_box, tmp_path):
    import tomllib

    project = tmp_path / "project"
    project.mkdir()
    path = profile_box / "profiles/standard.toml"
    path.write_text('name = "Standard"\ncomponents = ["ruff", "agents"]')
    result = invoke_profile(profile_box, project, "init", "-r", "standard", "-y")
    assert result.returncode == 0, result.stdout + result.stderr
    config = project / "kitflow.toml"
    document = tomllib.loads(config.read_text())
    assert document["selection"]["components"] == ["python", "ruff", "agents"]
    assert "profile" not in document["selection"]
    path.write_text('name = "Standard"\ncomponents = ["django"]')
    result = invoke_profile(profile_box, project, "update", "-y")
    assert result.returncode == 0, result.stdout + result.stderr
    assert tomllib.loads(config.read_text())["selection"]["components"] == [
        "python",
        "ruff",
        "agents",
    ]
    result = invoke_profile(profile_box, project, "init", "--profile", "standard", "-y")
    assert result.returncode == 0, result.stdout + result.stderr
    assert tomllib.loads(config.read_text())["selection"]["components"] == ["python", "django"]
    assert not (project / "ruff.toml").exists()
    assert (project / "PROJECT.md").exists()
    assert invoke_profile(profile_box, project, "init", "-c", "ruff", "-y").returncode == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ["init", "-r", "missing", "-y"],
        ["init", "-r", "standard", "-c", "ruff", "-y"],
        ["check", "-r", "standard"],
        ["config", "-r", "standard"],
        ["-r", "standard"],
        ["-i", "-r", "standard"],
    ],
)
def test_cli_rejects_invalid_profile_usage_without_writes(profile_box, tmp_path, arguments):
    project = tmp_path / "project"
    project.mkdir()
    (profile_box / "profiles/standard.toml").write_text('name = "Standard"\ncomponents = ["ruff"]')
    result = invoke_profile(profile_box, project, *arguments)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not list(project.iterdir())


def test_check_reports_each_invalid_profile_and_does_not_write(profile_box, tmp_path):
    from kitflow.check import configuration_issues

    project = tmp_path / "project"
    project.mkdir()
    paths = [profile_box / "profiles/one.toml", profile_box / "profiles/two.toml"]
    for path in paths:
        path.write_text('name = "Invalid"\ncomponents = ["missing"]')
    before = {p: p.read_bytes() for p in profile_box.rglob("*") if p.is_file()}
    issues = configuration_issues(profile_box, project)
    assert {p for p, _ in issues} == set(paths)
    assert {p: p.read_bytes() for p in before} == before
    assert not list(project.iterdir())


@pytest.mark.asyncio
async def test_profile_picker_review_customize_custom_and_cancel(profile_box):
    from kitflow.tui import ProfilePicker, SetupChoice

    (profile_box / "profiles/django.toml").write_text('name = "Django"\ncomponents = ["django"]')
    profiles = load_profiles(Catalog(profile_box))
    app = ProfilePicker(profiles)
    async with app.run_test(size=(100, 32)) as pilot:
        assert app.focused is app.query_one("#profiles")
        await pilot.press("down", "right")
        assert app.focused is app.query_one("#continue")
        await pilot.press("left")
        assert app.focused is app.query_one("#profiles")
        await pilot.press("enter", "enter")
    assert app.return_value == SetupChoice("django", False)
    app = ProfilePicker(profiles)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("down", "enter", "tab", "enter")
    assert app.return_value == SetupChoice("django", True)
    app = ProfilePicker(profiles)
    async with app.run_test() as pilot:
        await pilot.press("enter")
    assert app.return_value == SetupChoice(None, True)
    app = ProfilePicker(profiles)
    async with app.run_test() as pilot:
        await pilot.press("escape")
    assert app.return_value is None


@pytest.mark.parametrize(
    ("choice", "customize"), [("django", False), ("django", True), (None, True)]
)
def test_interactive_init_uses_profile_or_existing_selection(
    profile_box, tmp_path, monkeypatch, choice, customize
):
    import tomllib

    from kitflow import cli
    from kitflow.engine import apply, load_config, plan
    from kitflow.tui import Configurator, ProfilePicker, Selection, SetupChoice

    project = tmp_path / "project"
    project.mkdir()
    catalog = Catalog(profile_box)
    apply(plan(project, catalog, ["ruff"], load_config(project)), {})
    (profile_box / "profiles/django.toml").write_text('name = "Django"\ncomponents = ["django"]')
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.Confirm, "ask", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(ProfilePicker, "run", lambda _self: SetupChoice(choice, customize))
    seen = []

    def configure(app):
        seen.append(set(app.chosen))
        return Selection(catalog.resolve(sorted(app.chosen)), sorted(app.excluded))

    monkeypatch.setattr(Configurator, "run", configure)
    assert (
        cli.run(cli.parser().parse_args(["init", "-b", str(profile_box), "-p", str(project)])) == 0
    )
    expected = {"python", "django"} if choice else {"python", "ruff"}
    assert seen == ([expected] if customize else [])
    assert (
        set(tomllib.loads((project / "kitflow.toml").read_text())["selection"]["components"])
        == expected
    )


def test_interactive_profile_cancel_does_not_write(profile_box, tmp_path, monkeypatch):
    from kitflow import cli
    from kitflow.tui import ProfilePicker

    project = tmp_path / "project"
    project.mkdir()
    (profile_box / "profiles/django.toml").write_text('name = "Django"\ncomponents = ["django"]')
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(ProfilePicker, "run", lambda _self: None)
    assert (
        cli.run(cli.parser().parse_args(["init", "-b", str(profile_box), "-p", str(project)])) == 0
    )
    assert not list(project.iterdir())
