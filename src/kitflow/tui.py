"""Keyboard and mouse component selector; no disk writes in the UI."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Label, ListItem, ListView, SelectionList, Static

from kitflow.catalog import Catalog, KitFlowError
from kitflow.wizard import Step, Wizard


@dataclass
class Selection:
    components: list[str]
    excluded: list[str]


class Components(SelectionList[str]):
    BINDINGS = [Binding("enter", "select", "Select", show=False)]


class Configurator(App[Selection | None]):
    """Navigator: one conditional step at a time, with a persistent step list."""

    TITLE = "KitFlow"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #111714; color: #e4eee6; }
    #brand { height: 3; padding: 1 3 0 3; color: #9cddb2; }
    #body { height: 1fr; padding: 1 3; }
    #steps { width: 30; margin-right: 3; background: transparent; border-right: solid #36493c; }
    #steps ListItem { height: 3; padding: 1 1 0 1; }
    #steps ListItem.-highlight { background: #22342a; color: #9cddb2; }
    #right { width: 1fr; }
    #question { height: 2; text-style: bold; }
    #hint { height: auto; max-height: 4; margin-bottom: 1; color: #a5b8aa; }
    #components { height: 1fr; border: none; background: transparent; padding: 0; }
    #components > .option-list--option-highlighted { background: #22342a; color: #e4eee6; }
    #details { height: 4; padding: 1 0; color: #a5b8aa; }
    #review { height: 1fr; overflow-y: auto; }
    #summary { height: 2; padding: 0 3; color: #a5b8aa; }
    #buttons { height: 3; padding: 0 3; align-horizontal: right; }
    Button { margin-left: 1; min-width: 12; }
    Footer { background: #1b241e; }
    """
    BINDINGS = [
        Binding("left", "previous", "Back", priority=True),
        Binding("right", "next", "Next", priority=True),
        Binding("tab", "focus_buttons", "Actions", priority=True),
        Binding("ctrl+s", "review", "Review plan"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self, catalog: Catalog, selected: list[str], excluded: list[str], *, existing=False
    ):
        super().__init__()
        self.catalog = catalog
        self.model = Wizard(catalog, selected, excluded, existing=existing)
        self.steps = self.model.steps()
        self.position = 0
        self.refreshing = False

    @property
    def step(self) -> Step:
        return self.steps[self.position]

    def compose(self) -> ComposeResult:
        yield Static("kitflow / project setup", id="brand")
        with Horizontal(id="body"):
            yield ListView(id="steps")
            with Vertical(id="right"):
                yield Static("", id="question", markup=False)
                yield Static("", id="hint", markup=False)
                yield Components(id="components")
                yield Static("", id="review", markup=False)
                yield Static("", id="details", markup=False)
        yield Static("", id="summary", markup=False)
        with Horizontal(id="buttons"):
            yield Button("Cancel", id="cancel")
            yield Button("Back", id="back")
            yield Button("Next", variant="primary", id="next")
        yield Footer()

    async def on_mount(self):
        await self.refresh_step()
        self.query_one("#components").focus()

    async def refresh_step(self, highlighted=0):
        self.refreshing = True
        try:
            self.model.enter(self.step)
            current = self.step.id
            self.steps = self.model.steps()
            self.position = next(
                (i for i, step in enumerate(self.steps) if step.id == current),
                min(self.position, len(self.steps) - 1),
            )
            navigation = self.query_one("#steps", ListView)
            await navigation.clear()
            await navigation.extend(
                ListItem(
                    Label(
                        Text(
                            f"{'✓' if i < self.position else '›' if i == self.position else '·'} {step.label}"
                        )
                    )
                )
                for i, step in enumerate(self.steps)
            )
            navigation.index = self.position
            choices = self.query_one("#components", Components)
            with choices.prevent(SelectionList.SelectionToggled, SelectionList.SelectedChanged):
                choices.clear_options()
                if self.step.id == "ownership":
                    choices.add_options(
                        (Text(f"Manage again: {x}"), f"restore:{x}", False)
                        for x in sorted(self.model.excluded)
                    )
                else:
                    choices.add_options(
                        (
                            Text(
                                self.catalog.components[x].label
                                + (
                                    "  · recommended"
                                    if self.model.rows[x].get("recommended")
                                    else ""
                                )
                            ),
                            x,
                            x in self.model.chosen,
                        )
                        for x in self.model.choices(self.step)
                    )
            if choices.option_count:
                choices.highlighted = min(highlighted, choices.option_count - 1)
            reviewing = self.step.id == "review"
            choices.display = not reviewing
            self.query_one("#review").display = reviewing
            self.query_one("#details").display = not reviewing
            self.query_one("#question", Static).update(self.step.label)
            self.query_one("#hint", Static).update(
                self.step.description
                or (
                    "Review the selection. No files have been changed."
                    if reviewing
                    else "Enter toggles a choice. Right continues; Left goes back. All recommendations are optional."
                )
            )
            self.query_one("#review", Static).update(self.selection_summary())
            self.query_one("#summary", Static).update(
                f"Step {self.position + 1}/{len(self.steps)} · {len(self.model.chosen)} components selected"
            )
            self.query_one("#back", Button).disabled = self.position == 0
            self.query_one("#next", Button).label = "Review files" if reviewing else "Next"
            self.query_one("#details", Static).update("")
        finally:
            self.refreshing = False

    def selection_summary(self) -> str:
        groups: dict[str, list[str]] = {}
        for identity, component in self.catalog.components.items():
            if identity in self.model.chosen:
                groups.setdefault(component.category, []).append(component.label)
        return (
            "\n\n".join(f"{name}\n  {', '.join(items)}" for name, items in groups.items())
            or "No optional components selected."
        )

    @on(ListView.Selected, "#steps")
    async def choose_step(self, event: ListView.Selected):
        if self.refreshing:
            return
        target = event.list_view.index
        if target is not None:
            if target > self.position + 1:
                self.notify("Use Next to review each step. You can revisit previous steps.")
                event.list_view.index = self.position
                return
            self.position = target
            await self.refresh_step()
            self.focus_current()

    def focus_current(self):
        self.query_one("#next" if self.step.id == "review" else "#components").focus()

    @on(SelectionList.SelectionHighlighted, "#components")
    def describe(self, event: SelectionList.SelectionHighlighted):
        if self.refreshing:
            return
        identity = event.selection.value
        if identity.startswith("restore:"):
            description = "Return this artifact to KitFlow. Review differences before applying."
        else:
            component = self.catalog.components[identity]
            description = component.description
            if component.requires:
                description += "\nRequires: " + ", ".join(
                    self.catalog.components[x].label for x in component.requires
                )
        self.query_one("#details", Static).update(description)

    @on(SelectionList.SelectionToggled, "#components")
    async def toggle_component(self, event: SelectionList.SelectionToggled):
        if self.refreshing:
            return
        highlighted = self.query_one("#components", Components).highlighted or 0
        identity = event.selection.value
        if identity.startswith("restore:"):
            self.model.excluded.discard(identity.removeprefix("restore:"))
        else:
            try:
                added, removed = self.model.toggle(identity)
            except KitFlowError as error:
                self.notify(str(error), severity="error")
            else:
                dependencies = added - {identity}
                dependents = removed - {identity}
                if dependencies:
                    self.notify("Dependencies added: " + ", ".join(sorted(dependencies)))
                if dependents:
                    self.notify("Also removed: " + ", ".join(sorted(dependents)))
        await self.refresh_step(highlighted)
        self.focus_current()

    @on(Button.Pressed, "#back")
    async def action_previous(self):
        self.position = max(0, self.position - 1)
        await self.refresh_step()
        self.focus_current()

    @on(Button.Pressed, "#next")
    async def action_next(self):
        if self.step.id == "review":
            self.exit(
                Selection(
                    self.catalog.resolve(sorted(self.model.chosen)), sorted(self.model.excluded)
                )
            )
            return
        self.position += 1
        await self.refresh_step()
        self.focus_current()

    async def action_review(self):
        self.position = len(self.steps) - 1
        await self.refresh_step()
        self.focus_current()

    def action_focus_buttons(self):
        actions = [self.query_one(f"#{x}", Button) for x in ("next", "back", "cancel")]
        actions = [button for button in actions if not button.disabled]
        index = (
            next((i for i, button in enumerate(actions) if button is self.focused), -1) + 1
        ) % len(actions)
        actions[index].focus()

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.exit(None)
