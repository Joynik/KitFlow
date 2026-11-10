from pathlib import Path

import pytest
from textual.widgets import ListView

from kitflow.catalog import Catalog
from kitflow.tui import Components, Configurator


@pytest.mark.asyncio
async def test_keyboard_mouse_dependencies_and_cancel():
    catalog = Catalog(Path(__file__).parent / "fixtures/catalog")
    app = Configurator(catalog, [], [])
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("enter")
        assert "python" in app.chosen
        await pilot.press("enter")
        assert "python" not in app.chosen
        categories = app.query_one("#categories", ListView)
        categories.index = app.categories.index("Frameworks")
        await pilot.pause()
        app.query_one("#components").focus()
        await pilot.press("enter")
        assert {"django", "python"}.issubset(app.chosen)
        await pilot.click("#continue")
    assert app.return_value is not None
    assert app.return_value.components == ["python", "django"]
    app = Configurator(catalog, [], [])
    async with app.run_test() as pilot:
        await pilot.press("escape")
    assert app.return_value is None


@pytest.mark.asyncio
async def test_removing_dependency_removes_dependents_and_restore_exclusion():
    catalog = Catalog(Path(__file__).parent / "fixtures/catalog")
    app = Configurator(catalog, ["django", "ruff"], ["ruff"])
    async with app.run_test(size=(100, 32)) as pilot:
        app.query_one("#components", Components).highlighted = 0
        await pilot.press("enter")
        assert not app.chosen
        app.query_one("#categories", ListView).index = app.categories.index("User-owned files")
        await pilot.pause()
        app.query_one("#components").focus()
        await pilot.press("enter")
        assert "ruff" not in app.excluded
        await pilot.press("ctrl+s")
    assert app.return_value is not None
    assert app.return_value.excluded == []
