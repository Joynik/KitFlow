from pathlib import Path

import pytest
from textual.widgets import Button

from kitflow.catalog import Catalog
from kitflow.tui import Configurator


@pytest.mark.asyncio
async def test_navigator_selects_dependencies_reviews_and_returns_selection():
    catalog = Catalog(Path(__file__).parent / "fixtures/catalog")
    app = Configurator(catalog, [], [])
    async with app.run_test(size=(100, 32)) as pilot:
        assert app.focused is app.query_one("#components")
        await pilot.press("enter")
        assert app.model.chosen == {"python"}
        await pilot.press("right")
        assert app.step.label == "Frameworks"
        await pilot.press("enter")
        assert app.model.chosen == {"python", "django"}
        await pilot.press("left")
        assert app.step.label == "Languages"
        await pilot.press("ctrl+s")
        assert app.step.id == "review"
        assert not app.query_one("#components").display
        await pilot.click("#next")
    assert app.return_value is not None
    assert app.return_value.components == ["python", "django"]


@pytest.mark.asyncio
async def test_navigator_mouse_and_dependency_removal_preserve_exclusions():
    catalog = Catalog(Path(__file__).parent / "fixtures/catalog")
    app = Configurator(catalog, ["django", "ruff"], ["ruff"], existing=True)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("enter")
        assert not app.model.chosen
        await pilot.click("#next")
        assert app.step.label == "Instructions"
        await pilot.click("#next")
        assert app.step.id == "ownership"
        await pilot.press("enter")
        assert not app.model.excluded
        await pilot.press("ctrl+s", "right")
    assert app.return_value is not None
    assert app.return_value.components == []
    assert app.return_value.excluded == []


@pytest.mark.asyncio
async def test_navigator_cancel_and_button_navigation():
    app = Configurator(Catalog(Path(__file__).parent / "fixtures/catalog"), [], [])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("tab")
        assert app.focused is app.query_one("#next", Button)
        await pilot.press("escape")
    assert app.return_value is None


@pytest.mark.asyncio
async def test_optional_recommendation_stays_off_after_back_navigation(tmp_path):
    import shutil

    shutil.copytree(Path(__file__).parent / "fixtures/catalog", tmp_path / "box")
    manifest = tmp_path / "box/kitflow-box.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'id = "ruff"\nlabel', 'id = "ruff"\nrecommended = true\nlabel', 1
        )
    )
    catalog = Catalog(tmp_path / "box")
    app = Configurator(catalog, [], [])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter", "right", "right")
        assert app.step.label == "Checks"
        assert "ruff" in app.model.chosen
        await pilot.press("enter", "left", "right")
        assert "ruff" not in app.model.chosen
        await pilot.press("escape")
    app = Configurator(catalog, ["python"], [], existing=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("right", "right")
        assert "ruff" not in app.model.chosen
        await pilot.press("escape")
