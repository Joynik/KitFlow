"""Keyboard and mouse component selector; no disk writes in the UI."""

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, SelectionList, Static

from kitflow.catalog import Catalog, KitFlowError


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
            "Choose components. Enter or Space toggles; Tab changes the focused area.",
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
        self.query_one("#components").focus()

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
