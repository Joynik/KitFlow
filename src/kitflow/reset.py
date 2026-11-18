"""Build selectable reset edits and translate the selection into the guarded plan."""

import difflib
import tomllib
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

import tomlkit

from kitflow import mise
from kitflow.catalog import KitFlowError
from kitflow.engine import Change, Plan, preview_files, update_mise


@dataclass(frozen=True)
class Hunk:
    start: int
    end: int
    replacement: list[bytes]


@dataclass(frozen=True)
class Edit:
    label: str
    before: str
    after: str
    change: Change | None = None
    hunk: Hunk | None = None


def display(value: bytes | str | None) -> str:
    if isinstance(value, str):
        return f"Symbolic link → {value}"
    if value is None:
        return ""
    try:
        if b"\0" not in value:
            return value.decode("utf-8")
    except UnicodeError:
        pass
    return "Binary file"


def text_edits(before: bytes, after: bytes) -> list[Edit]:
    if b"\0" in before or b"\0" in after:
        return []
    try:
        before.decode("utf-8")
        after.decode("utf-8")
    except UnicodeError:
        return []
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    edits = []
    for group in difflib.SequenceMatcher(None, old, new, autojunk=False).get_grouped_opcodes(2):
        modified = [opcode for opcode in group if opcode[0] != "equal"]
        if not modified:
            continue
        _, start, _, new_start, _ = modified[0]
        _, _, end, _, new_end = modified[-1]
        action = "Add" if start == end else "Remove" if new_start == new_end else "Replace"
        location = f"after line {start}" if start == end else f"lines {start + 1}–{end}"
        edits.append(
            Edit(
                f"{action} · {location}",
                display(b"".join(old[group[0][1] : group[-1][2]])),
                display(b"".join(new[group[0][3] : group[-1][4]])),
                hunk=Hunk(start, end, new[new_start:new_end]),
            )
        )
    return edits


def setting_edits(change: Change, before: str, after: str) -> list[Edit]:
    edits = []
    old_doc, new_doc = tomlkit.parse(before), tomlkit.parse(after)
    missing = object()

    def snippet(path, value):
        if value is missing:
            return b""
        document = tomlkit.document()
        table = document
        for key in path[:-1]:
            table[key] = tomlkit.table()
            table = table[key]
        table[path[-1]] = value
        return tomlkit.dumps(document).encode()

    def walk(old, new, path):
        if type(old) is type(new) and old == new:
            return
        if isinstance(new, dict) and new and (old is missing or isinstance(old, dict)):
            for key, value in new.items():
                walk(
                    old.get(key, missing) if isinstance(old, dict) else missing, value, (*path, key)
                )
            return
        content = snippet(path, new)
        edits.append(
            Edit(
                f"{'Add' if old is missing else 'Reset'} · {'.'.join(path)}",
                display(snippet(path, old)),
                display(content),
                change=replace(change, after=content),
            )
        )

    for section in new_doc:
        if section in {"vars", "env", "settings"}:
            walk(old_doc.get(section, missing), new_doc[section], (section,))
    return edits


def mise_edits(changes: list[Change], before: bytes | None) -> list[Edit]:
    current = (before or b"").decode()
    defaults = [change for change in changes if change.operation == "reset-defaults"]
    edits = []
    if defaults:
        updated = current
        for change in defaults:
            updated = update_mise(updated, change)
        if updated != current:
            edits.extend(setting_edits(defaults[-1], current, updated))
            if not edits:
                edits.append(Edit("Reset · settings formatting", current, updated))
    for change in changes:
        if change.artifact.kind not in {"task", "env"}:
            continue
        artifact = change.artifact
        action = "Add" if change.before is None else "Reset"
        edits.append(
            Edit(f"{action} · {artifact.id}", display(change.before), display(change.after), change)
        )
    return edits


@dataclass
class ResetFile:
    changes: list[Change]
    edits: list[Edit]

    def selected_changes(self, selected: set[int]) -> list[Change]:
        if not selected:
            return []
        if len(selected) == len(self.edits):
            return self.changes
        edits = [edit for index, edit in enumerate(self.edits) if index in selected]
        original = self.changes[0]
        if original.artifact.path == "mise.toml":
            defaults = [
                edit.change
                for edit in edits
                if edit.change and edit.change.operation == "reset-defaults"
            ]
            if any(edit.change is None for edit in edits):
                defaults = [
                    change for change in self.changes if change.operation == "reset-defaults"
                ]
            # Merge selected keys into one reset operation before applying task changes.
            if defaults and all(edit.change is not None for edit in edits):
                content = ""
                for change in defaults:
                    content = update_mise(content, change)
                defaults = [replace(defaults[-1], after=content.encode())]
            return [
                *defaults,
                *(
                    edit.change
                    for edit in edits
                    if edit.change and edit.change.operation != "reset-defaults"
                ),
            ]

        assert isinstance(original.before, bytes)
        lines = original.before.splitlines(keepends=True)
        for edit in reversed(edits):
            assert edit.hunk is not None
            hunk = edit.hunk
            lines[hunk.start : hunk.end] = hunk.replacement
        return [replace(original, after=b"".join(lines), state_baseline=original.after)]


def reset_files(result: Plan) -> dict[str, ResetFile]:
    changes_by_path = defaultdict(list)
    for change in result.changes:
        if change.operation not in {"detach", "adopt", "forget"}:
            changes_by_path[change.artifact.path].append(change)
    files = {}
    for name, (before, after) in preview_files(result).items():
        changes = changes_by_path[name]
        base = changes[0]
        if name == "mise.toml":
            assert before is None or isinstance(before, bytes)
            edits = mise_edits(changes, before)
        elif isinstance(base.before, bytes) and isinstance(base.after, bytes):
            edits = text_edits(base.before, base.after)
        else:
            edits = []
        if not edits:
            action = (
                "Add file" if before is None else "Remove file" if after is None else "Replace file"
            )
            edits = [Edit(action, display(before), display(after))]
        files[name] = ResetFile(changes, edits)
    return files


def select_reset(result: Plan, files: dict[str, ResetFile], selected: dict[str, set[int]]):
    changes = [
        change
        for name, file in files.items()
        for change in file.selected_changes(selected.get(name, set()))
    ]
    chosen = replace(result, changes=changes)
    for name, (_, content) in preview_files(chosen).items():
        if PurePosixPath(name).suffix == ".toml" and isinstance(content, bytes):
            try:
                tomllib.loads(content.decode())
                if name == "mise.toml":
                    mise.blocks(content.decode())
            except (ValueError, UnicodeError) as error:
                raise KitFlowError(
                    f"Selected changes would produce invalid TOML in {name}: {error}"
                ) from error
    result.changes = changes
