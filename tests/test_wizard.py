import pytest

from kitflow.catalog import Catalog, KitFlowError
from kitflow.wizard import Wizard


@pytest.fixture
def wizard_box(tmp_path):
    (tmp_path / "kitflow-box.toml").write_text("""schema = 3
[[steps]]
id = "languages"
label = "Languages"
categories = ["Languages"]
order = 10
[[steps]]
id = "frameworks"
label = "Frameworks"
categories = ["Frameworks"]
order = 20
[[components]]
id = "language"
label = "Language"
category = "Languages"
[[components]]
id = "framework"
label = "Framework"
category = "Frameworks"
requires = ["language"]
conflicts = ["alternative"]
[[components]]
id = "alternative"
label = "Alternative"
category = "Frameworks"
requires = ["language"]
[[components]]
id = "check"
label = "Check"
category = "Checks"
requires = ["framework"]
recommended = true
[[components]]
id = "markdown"
label = "Markdown"
category = "Checks"
recommended = true
""")
    return tmp_path


def test_steps_follow_selection_and_recommendations_stay_optional(wizard_box):
    model = Wizard(Catalog(wizard_box), [], [])
    assert [s.label for s in model.steps()] == ["Languages", "Checks", "Review plan"]
    model.toggle("language")
    assert "Frameworks" in [s.label for s in model.steps()]
    model.toggle("framework")
    step = next(s for s in model.steps() if s.label == "Checks")
    model.enter(step)
    assert {"check", "markdown"}.issubset(model.chosen)
    model.toggle("check")
    model.enter(step)
    assert "check" not in model.chosen
    model.toggle("alternative")
    assert model.chosen == {"language", "alternative", "markdown"}
    model.toggle("language")
    assert model.chosen == {"markdown"}


def test_existing_selection_does_not_gain_old_recommendations(wizard_box):
    model = Wizard(Catalog(wizard_box), ["framework"], [], existing=True)
    model.enter(next(s for s in model.steps() if s.label == "Checks"))
    assert model.chosen == {"language", "framework"}
    model = Wizard(Catalog(wizard_box), ["language"], [], existing=True)
    model.toggle("framework")
    model.enter(next(s for s in model.steps() if s.label == "Checks"))
    assert "check" in model.chosen
    assert "markdown" not in model.chosen


def test_visibility_is_separate_from_required_dependencies(wizard_box):
    path = wizard_box / "kitflow-box.toml"
    path.write_text(
        path.read_text()
        + """
[[components]]
id = "application"
label = "Application"
category = "Frameworks"
requires = ["framework"]
when = ["language"]
"""
    )
    model = Wizard(Catalog(wizard_box), ["language"], [])
    step = next(step for step in model.steps() if step.label == "Frameworks")
    assert "application" in model.choices(step)
    model.toggle("application")
    assert {"application", "framework", "language"}.issubset(model.chosen)
    model.toggle("language")
    assert not model.chosen


@pytest.mark.parametrize(
    "replacement",
    [
        ("recommended = true", 'recommended = "yes"'),
        ("order = 10", 'order = "first"'),
        ('id = "languages"', 'id = "review"'),
        ('categories = ["Frameworks"]', 'categories = ["Languages"]'),
        ("order = 10", 'order = 10\nwhen = ["missing"]'),
    ],
)
def test_invalid_wizard_definitions_are_rejected(wizard_box, replacement):
    path = wizard_box / "kitflow-box.toml"
    path.write_text(path.read_text().replace(*replacement))
    with pytest.raises(KitFlowError):
        Catalog(wizard_box)
