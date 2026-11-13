"""Keyboard and mouse component selector; no disk writes in the UI."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, SelectionList, Static

from kitflow.catalog import Catalog, KitFlowError
from kitflow.profiles import Profile


@dataclass
class Selection:
    components: list[str]
    excluded: list[str]


class Components(SelectionList[str]):
    BINDINGS = [Binding("enter", "select", "Select", show=False)]


class Configurator(App[Selection | None]):
    TITLE = "KitFlow"
    SUB_TITLE = "Project configuration"
    CSS = """
    Screen { background: #172333; color: #e4eaf2; }
    Header { background: #24384d; }
    #intro { height: 3; padding: 1 2 0 2; color: #b5c8da; }
    #body { height: 1fr; padding: 1 2; }
    #categories { width: 24; margin-right: 2; background: #203248; }
    #categories ListItem { padding: 1; }
    #right { width: 1fr; }
    #components { height: 1fr; border: round #5d8fa9; background: #203248; }
    #details { height: 5; padding: 1; color: #b5c8da; }
    #summary { height: 3; padding: 0 2; color: #90d6cf; }
    #buttons { height: 3; padding: 0 2; align-horizontal: right; }
    Button { margin-left: 1; }
    Footer { background: #24384d; }
    """
    BINDINGS = [
        Binding("left", "focus_categories", "Categories", priority=True),
        Binding("right", "focus_components", "Components", priority=True),
        Binding("tab", "focus_buttons", "Buttons", priority=True),
        Binding("ctrl+s", "continue", "Review plan"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, catalog: Catalog, selected: list[str], excluded: list[str]):
        super().__init__()
        self.catalog = catalog
        self.chosen = set(catalog.resolve(selected))
        self.excluded = set(excluded)
        self.categories = list(dict.fromkeys(c.category for c in catalog.components.values()))
        if excluded:
            self.categories.append("User-owned files")
        self.category = self.categories[0]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Choose components. Left/Right switches lists; Enter toggles; Tab reaches buttons.",
            id="intro",
        )
        with Horizontal(id="body"):
            yield ListView(
                *(ListItem(Label(Text(name))) for name in self.categories), id="categories"
            )
            with Vertical(id="right"):
                yield Components(id="components")
                yield Static("", id="details", markup=False)
        yield Static("", id="summary", markup=False)
        with Horizontal(id="buttons"):
            yield Button("Cancel", id="cancel")
            yield Button("Review plan", variant="primary", id="continue")
        yield Footer()

    def on_mount(self):
        self.refresh_choices()
        self.query_one("#categories").focus()

    def action_focus_categories(self):
        self.query_one("#categories").focus()

    def action_focus_components(self):
        self.query_one("#components").focus()

    def action_focus_buttons(self):
        review = self.query_one("#continue")
        self.query_one("#cancel" if self.focused is review else "#continue").focus()

    def refresh_choices(self, highlighted: int = 0):
        choices = self.query_one("#components", Components)
        with choices.prevent(SelectionList.SelectionToggled, SelectionList.SelectedChanged):
            choices.clear_options()
            if self.category == "User-owned files":
                choices.add_options(
                    (Text(f"Manage again: {identity}"), f"restore:{identity}", False)
                    for identity in sorted(self.excluded)
                )
            else:
                choices.add_options(
                    (Text(component.label), component.id, component.id in self.chosen)
                    for component in self.catalog.components.values()
                    if component.category == self.category
                )
        if choices.option_count:
            choices.highlighted = min(highlighted, choices.option_count - 1)
        self.query_one("#summary", Static).update(
            f"Selected: {', '.join(self.catalog.components[x].label for x in self.catalog.components if x in self.chosen) or 'none'}"
        )

    @on(ListView.Highlighted, "#categories")
    def category_changed(self, event: ListView.Highlighted):
        if event.list_view.index is not None:
            self.category = self.categories[event.list_view.index]
            self.refresh_choices()

    @on(SelectionList.SelectionHighlighted, "#components")
    def describe(self, event: SelectionList.SelectionHighlighted):
        identity = event.selection.value
        if identity.startswith("restore:"):
            text = "Return this file or block to KitFlow. Review differences before applying."
        else:
            component = self.catalog.components[identity]
            text = component.description
            if component.requires:
                text += "\nRequires: " + ", ".join(component.requires)
        self.query_one("#details", Static).update(text)

    @on(SelectionList.SelectionToggled, "#components")
    def toggle_component(self, event: SelectionList.SelectionToggled):
        highlighted = self.query_one("#components", Components).highlighted or 0
        identity = event.selection.value
        if identity.startswith("restore:"):
            self.excluded.discard(identity.removeprefix("restore:"))
        else:
            before = self.chosen.copy()
            if identity in self.chosen:
                self.chosen.remove(identity)
                removed = {identity}
                while True:
                    dependent = {
                        x
                        for x in self.chosen
                        if removed.intersection(self.catalog.components[x].requires)
                    }
                    if not dependent:
                        break
                    self.chosen -= dependent
                    removed |= dependent
                if len(removed) > 1:
                    self.notify("Also removed: " + ", ".join(sorted(removed - {identity})))
            else:
                try:
                    self.chosen = set(self.catalog.resolve(sorted(self.chosen | {identity})))
                except KitFlowError as error:
                    self.chosen = before
                    self.notify(str(error), severity="error")
                added = self.chosen - before - {identity}
                if added:
                    self.notify("Dependencies added: " + ", ".join(sorted(added)))
        self.refresh_choices(highlighted)

    @on(Button.Pressed, "#continue")
    def action_continue(self):
        self.exit(Selection(self.catalog.resolve(sorted(self.chosen)), sorted(self.excluded)))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.exit(None)


@dataclass(frozen=True)
class SetupChoice:
    profile: str | None
    customize: bool


class ProfilePicker(App[SetupChoice | None]):
    TITLE = "KitFlow"
    SUB_TITLE = "Choose a setup"
    CSS = (
        Configurator.CSS
        + """
    #profiles { height: 1fr; margin: 1 2; background: #203248; border: round #5d8fa9; }
    #profiles ListItem { padding: 0 1; }
    #details { height: 6; padding: 1 2; }
    """
    )
    BINDINGS = [
        Binding("left", "focus_profiles", "Setups", priority=True),
        Binding("right", "choose", "Open", priority=True),
        Binding("tab", "focus_buttons", "Actions", priority=True),
        Binding("ctrl+s", "review", "Review plan"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, profiles: dict[str, Profile]):
        super().__init__()
        self.profiles = profiles
        self.profile_ids = [None, *profiles]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Choose a setup. Enter/Right opens actions; Left returns to setups.", id="intro"
        )
        yield ListView(
            ListItem(Label("Custom setup")),
            *(ListItem(Label(Text(profile.name))) for profile in self.profiles.values()),
            id="profiles",
        )
        yield Static("", id="details", markup=False)
        with Horizontal(id="buttons"):
            yield Button("Cancel", id="cancel")
            yield Button("Customize selection", id="customize")
            yield Button("Review plan", variant="primary", id="continue", disabled=True)
        yield Footer()

    @property
    def selected_profile(self) -> str | None:
        index = self.query_one("#profiles", ListView).index or 0
        return self.profile_ids[index]

    def on_mount(self):
        self.query_one("#profiles").focus()
        self.show_details()

    @on(ListView.Highlighted, "#profiles")
    def show_details(self):
        identity = self.selected_profile
        review = self.query_one("#continue", Button)
        review.disabled = identity is None
        if identity is None:
            text = (
                "Choose components manually. An existing project's current selection is preserved."
            )
        else:
            profile = self.profiles[identity]
            text = f"{profile.description}\nProfile: {identity}\nComponents: {', '.join(profile.components) or 'none'}"
        self.query_one("#details", Static).update(text)

    @on(ListView.Selected, "#profiles")
    def action_choose(self):
        if self.selected_profile is None:
            self.action_customize()
        else:
            self.query_one("#continue").focus()

    def action_focus_profiles(self):
        self.query_one("#profiles").focus()

    def action_focus_buttons(self):
        actions = (
            ["continue", "customize", "cancel"]
            if self.selected_profile
            else ["customize", "cancel"]
        )
        buttons = [self.query_one(f"#{identity}") for identity in actions]
        index = (buttons.index(self.focused) + 1) % len(buttons) if self.focused in buttons else 0
        buttons[index].focus()

    @on(Button.Pressed, "#continue")
    def action_review(self):
        if self.selected_profile is not None:
            self.exit(SetupChoice(self.selected_profile, False))

    @on(Button.Pressed, "#customize")
    def action_customize(self):
        self.exit(SetupChoice(self.selected_profile, True))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.exit(None)
