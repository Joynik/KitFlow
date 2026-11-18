"""Keyboard and mouse component selector; no disk writes in the UI."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.theme import Theme
from textual.widgets import Button, Footer, Label, ListItem, ListView, SelectionList, Static

from kitflow.catalog import Catalog, KitFlowError
from kitflow.reset import Edit, ResetFile
from kitflow.wizard import Step, Wizard

CONTROLS_CSS = """
* {
    scrollbar-color: #456953;
    scrollbar-color-hover: #699778;
    scrollbar-color-active: #9cddb2;
    scrollbar-background: #172019;
    scrollbar-background-hover: #172019;
    scrollbar-background-active: #172019;
    scrollbar-corner-color: #172019;
    scrollbar-size: 1 1;
}
Button {
    height: 3;
    min-width: 10;
    margin-left: 1;
    padding: 0 1;
    background: #19251d;
    color: #c7dece;
    border: round #456953;
}
Button:hover { background: #294536; border: round #699778; }
Button:focus { border: round #b8e6c6; text-style: bold; }
Button.-primary {
    background: #274a33;
    color: #c1f9ce;
    border: round #63ad76;
    text-style: bold;
}
Button.-primary:hover { background: #365e41; }
Button.-primary:focus { border: round #c1f9ce; }
Button:disabled, Button:disabled:hover {
    background: #172019;
    color: #829187;
    border: round #2c3d32;
    text-style: none;
}
Footer { background: #1b241e; }
Components > .selection-list--button-selected,
Components > .selection-list--button-selected-highlighted {
    color: #111714; background: #50fa7b; text-style: bold;
}
"""


class KitFlowApp[Result](App[Result]):
    def __init__(self):
        super().__init__()
        self.register_theme(
            Theme(
                name="kitflow",
                primary="#699778",
                secondary="#456953",
                accent="#9cddb2",
                foreground="#e4eee6",
                background="#111714",
                surface="#19251d",
                panel="#456953",
                variables={
                    "block-cursor-background": "#294536",
                    "block-cursor-blurred-background": "#22342a",
                },
            )
        )
        self.theme = "kitflow"


@dataclass
class Selection:
    components: list[str]
    excluded: list[str]


class Components(SelectionList[str]):
    BINDINGS = [Binding("enter", "select", "Select", show=False)]


class Configurator(KitFlowApp[Selection | None]):
    """Navigator: one conditional step at a time, with a persistent step list."""

    TITLE = "KitFlow"
    ENABLE_COMMAND_PALETTE = False
    CSS = (
        CONTROLS_CSS
        + """
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
    #details { height: 4; padding: 1 0; color: #a5b8aa; }
    #review { height: 1fr; overflow-y: auto; }
    #summary { height: 2; padding: 0 3; color: #a5b8aa; }
    #buttons { height: 3; padding: 0 3; align-horizontal: right; }
    """
    )
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


class ActionMenu(KitFlowApp[str | None]):
    """Choose an action with arrows, Enter or the mouse."""

    ENABLE_COMMAND_PALETTE = False
    CSS = (
        CONTROLS_CSS
        + """
    Screen { align: center middle; background: #111714; color: #e4eee6; }
    #menu { width: 72; max-width: 95%; height: auto; border: round #50fa7b; padding: 1 2; }
    #title { height: auto; margin-bottom: 1; text-style: bold; }
    ListView { height: auto; max-height: 12; background: transparent; }
    ListItem { height: 3; padding: 1; }
    ListItem.-highlight { background: #294536; color: #50fa7b; text-style: bold; }
    #keys { height: 1; margin-top: 1; color: #a5b8aa; }
    """
    )
    BINDINGS = [Binding("escape", "cancel", "Exit")]

    def __init__(self, title: str, options: list[tuple[str, str]], default: str):
        super().__init__()
        self.heading, self.options, self.default = title, options, default

    def compose(self) -> ComposeResult:
        with Vertical(id="menu"):
            yield Static(self.heading, id="title", markup=False)
            yield ListView(*(ListItem(Label(label)) for _, label in self.options), id="actions")
            yield Static("↑/↓ Choose · Enter Select · Esc Exit", id="keys")

    def on_mount(self):
        actions = self.query_one(ListView)
        actions.index = next(
            i for i, (value, _) in enumerate(self.options) if value == self.default
        )
        actions.focus()

    @on(ListView.Selected)
    def select_action(self, event: ListView.Selected):
        if event.list_view.index is not None:
            self.exit(self.options[event.list_view.index][0])

    def action_cancel(self):
        self.exit(None)


class ResetFiles(KitFlowApp[dict[str, set[int]] | None]):
    """Review current and proposed changes and confirm an explicit selection."""

    ENABLE_COMMAND_PALETTE = False
    CSS = (
        CONTROLS_CSS
        + """
    Screen { background: #111714; color: #e4eee6; padding: 0 2; }
    #title { height: 2; text-style: bold; }
    #overview, #diff { height: 1fr; }
    #files { height: 1fr; }
    #edits { height: auto; min-height: 2; max-height: 8; }
    #panes { height: 1fr; layout: horizontal; }
    #panes.stacked { layout: vertical; }
    .pane { width: 1fr; height: 1fr; overflow: auto auto; border: round #496454; padding: 0 1; }
    #panes.stacked .pane { width: 100%; }
    .pane Label { text-style: bold; color: #b8e6c6; }
    .pane Static { width: auto; min-width: 100%; }
    #buttons { height: 3; align-horizontal: right; }
    """
    )
    BINDINGS = [
        Binding("right", "expand", "Review file", priority=True),
        Binding("left", "collapse", "Back to files", priority=True),
        Binding("enter", "enter", "Review / toggle", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, candidates: dict[str, ResetFile]):
        super().__init__()
        self.candidates = candidates
        self.selected: dict[str, set[int]] = {}
        self.current_file: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Review and update files", id="title", markup=False)
        with Vertical(id="overview"):
            yield Components(
                *((self.file_prompt(name), name, False) for name in self.candidates), id="files"
            )
        with Vertical(id="diff"):
            yield Components(id="edits")
            with Horizontal(id="panes"):
                with VerticalScroll(classes="pane"):
                    yield Label("Current project")
                    yield Static("", id="before", markup=False)
                with VerticalScroll(classes="pane"):
                    yield Label("Proposed by KitFlow")
                    yield Static("", id="after", markup=False)
        with Horizontal(id="buttons"):
            yield Button("Review file", id="review")
            yield Button("Back", id="back")
            yield Button("Cancel", id="cancel")
            yield Button("Apply selected", id="replace", variant="primary", disabled=True)
        yield Footer()

    def on_mount(self):
        self.action_collapse()

    def on_resize(self, event: Resize):
        panes = self.query("#panes")
        if panes:
            panes.first().set_class(event.size.width < 88, "stacked")

    def file_prompt(self, name: str) -> Text:
        total = len(self.candidates[name].edits)
        count = len(self.selected.get(name, ()))
        label = Text(name)
        if name != "mise.toml" and any(
            change.artifact.once for change in self.candidates[name].changes
        ):
            label.append("  Creation-only", style="#e9c88c")
        label.append(f"  {count}/{total} selected", style="#a6c4af")
        return label

    def record(self, name: str, selected: set[int]):
        if selected:
            self.selected[name] = selected
        else:
            self.selected.pop(name, None)
        files = self.query_one("#files", Components)
        if len(selected) == len(self.candidates[name].edits):
            files.select(name)
        else:
            files.deselect(name)
        index = list(self.candidates).index(name)
        files.replace_option_prompt_at_index(index, self.file_prompt(name))
        count = sum(map(len, self.selected.values()))
        button = self.query_one("#replace", Button)
        button.disabled = count == 0
        button.label = f"Apply selected ({count})" if count else "Apply selected"

    @on(SelectionList.SelectionToggled, "#files")
    def file_toggled(self, event: SelectionList.SelectionToggled):
        name = str(event.selection.value)
        checked = name in self.query_one("#files", Components).selected
        self.record(name, set(range(len(self.candidates[name].edits))) if checked else set())

    @on(SelectionList.SelectionToggled, "#edits")
    def edit_toggled(self):
        if self.current_file is not None:
            self.record(
                self.current_file,
                {int(value) for value in self.query_one("#edits", Components).selected},
            )

    def action_enter(self):
        if self.focused is self.query_one("#files"):
            self.action_expand()
        elif self.focused is self.query_one("#edits"):
            self.query_one("#edits", Components).action_select()
        elif isinstance(self.focused, Button):
            self.focused.press()

    @on(Button.Pressed, "#review")
    def action_expand(self):
        if self.current_file is not None:
            return
        choices = self.query_one("#files", Components)
        if choices.highlighted is None:
            return
        name = choices.get_option_at_index(choices.highlighted).value
        self.current_file = name
        self.query_one("#title", Static).update(Text(name))
        self.query_one("#overview").display = False
        self.query_one("#diff").display = True
        self.query_one("#review").display = False
        self.query_one("#back").display = True
        entries = self.query_one("#edits", Components)
        entries.clear_options()
        entries.add_options(
            (Text(edit.label), str(index), index in self.selected.get(name, ()))
            for index, edit in enumerate(self.candidates[name].edits)
        )
        entries.highlighted = 0
        entries.focus()
        self.show_edit(self.candidates[name].edits[0])

    @on(SelectionList.SelectionHighlighted, "#edits")
    def edit_highlighted(self, event: SelectionList.SelectionHighlighted):
        if self.current_file is not None:
            self.show_edit(self.candidates[self.current_file].edits[int(event.selection.value)])

    def show_edit(self, edit: Edit):
        old, new = edit.before.splitlines(keepends=True), edit.after.splitlines(keepends=True)
        before, after = Text(no_wrap=True), Text(no_wrap=True)
        for tag, i, j, start, end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            before.append("".join(old[i:j]), "#ff9c9d on #352022" if tag != "equal" else "")
            after.append("".join(new[start:end]), "#92e6a6 on #193626" if tag != "equal" else "")
        for identifier, content in (("#before", before), ("#after", after)):
            panel = self.query_one(identifier, Static)
            panel.update(content if content else Text("(none)", style="dim"))
            scroll = panel.parent
            if isinstance(scroll, VerticalScroll):
                scroll.scroll_home(animate=False)

    @on(Button.Pressed, "#back")
    def action_collapse(self):
        self.current_file = None
        self.query_one("#title", Static).update("Review and update files")
        self.query_one("#overview").display = True
        self.query_one("#diff").display = False
        self.query_one("#review").display = True
        self.query_one("#back").display = False
        self.query_one("#files").focus()

    @on(Button.Pressed, "#replace")
    def replace_selected(self):
        if self.selected:
            self.exit(self.selected)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.exit(None)
