"""KitFlow command line entry point."""

import argparse
import difflib
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from kitflow.catalog import KitFlowError
from kitflow.engine import CONFIG, apply, load_config, plan
from kitflow.settings import box_path, config_directory
from kitflow.source import load_box

console = Console(highlight=False)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="KitFlow — project standards over mise")
    result.add_argument("--version", action="version", version="KitFlow 0.1.0")
    result.add_argument(
        "command", nargs="?", choices=["init", "update", "status", "diff", "config"]
    )
    result.add_argument("--project", type=Path, default=Path.cwd(), help="Project directory")
    result.add_argument("--catalog", type=Path, help="Use a local box for this operation")
    result.add_argument("--components", help="Comma-separated component IDs for init")
    result.add_argument(
        "--manage",
        action="append",
        default=[],
        help="Return an excluded artifact to management (init)",
    )
    result.add_argument(
        "--yes", "-y", action="store_true", help="Confirm plan; never overwrite conflicts"
    )
    return result


def show_diff(change):
    before = (change.before or b"").decode(errors="replace").splitlines(keepends=True)
    after = (change.after or b"").decode(errors="replace").splitlines(keepends=True)
    difference = "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"current/{change.artifact.path}",
            tofile=f"catalog/{change.artifact.path}",
        )
    )
    if difference:
        console.print(Syntax(difference, "diff", word_wrap=True))


def show_plan(result):
    table = Table(title="KitFlow · Review plan", expand=True)
    table.add_column("Action", width=12)
    table.add_column("File / block")
    table.add_column("Status")
    for change in result.changes:
        table.add_row(
            change.operation,
            f"{change.artifact.path} · {change.artifact.id}",
            "Conflict" if change.conflict else change.reason or "Ready",
        )
    console.print(table)
    if not result.changes:
        console.print("Files match the selected components.")


def run(args: argparse.Namespace) -> int:
    if args.command == "config":
        if args.catalog or args.components is not None or args.manage or args.yes:
            raise KitFlowError(
                "config displays the user configuration location; it accepts no options"
            )
        console.print(f"Configuration: {config_directory()}", markup=False)
        console.print(f"Local box: {box_path()}", markup=False)
        return 0
    root = args.project.resolve()
    if not root.is_dir():
        raise KitFlowError(f"Project directory does not exist: {root}")
    exists = (root / CONFIG).exists()
    command = args.command or "init"
    if command != "init" and not exists:
        raise KitFlowError("Run kitflow init first")
    if args.components is not None and command != "init":
        raise KitFlowError("--components is available only for init")
    if args.manage and command != "init":
        raise KitFlowError("--manage is available only for init")
    if (
        command == "init"
        and args.components is None
        and not args.manage
        and (not sys.stdin.isatty() or args.yes)
    ):
        raise KitFlowError("Use --components for non-interactive init")
    document = load_config(root)
    catalog, source = load_box(args.catalog)
    selection = document["selection"]
    selected = list(selection.get("components", []))
    excluded = list(selection.get("excluded", []))
    if args.manage:
        unknown = set(args.manage) - set(excluded)
        if unknown:
            raise KitFlowError(f"Not excluded: {', '.join(sorted(unknown))}")
        excluded = [x for x in excluded if x not in args.manage]
    if command == "init":
        if args.components is not None:
            selected = [x.strip() for x in args.components.split(",") if x.strip()]
        elif not args.manage:
            if not sys.stdin.isatty() or args.yes:
                raise KitFlowError("Use --components for non-interactive init")
            from kitflow.tui import Configurator

            chosen = Configurator(catalog, selected, excluded).run()
            if chosen is None:
                console.print("Cancelled. No files were changed.")
                return 0
            selected, excluded = chosen.components, chosen.excluded
    selection["excluded"] = excluded
    result = plan(root, catalog, selected, document)
    console.print(f"Project: {root}", markup=False)
    console.print(f"Box: {catalog.root}", markup=False)
    show_plan(result)
    if command == "diff":
        for change in result.changes:
            show_diff(change)
        return 1 if result.changes else 0
    if command == "status":
        return 1 if result.changes else 0
    for change in result.changes:
        if not change.conflict:
            continue
        show_diff(change)
        if args.yes or not sys.stdin.isatty():
            console.print("Conflicts remain. Run interactively; no files were changed.")
            return 2
        answer = Prompt.ask(
            "replace: apply; skip: skip this update; keep: stop managing; quit: cancel",
            choices=["replace", "skip", "keep", "quit"],
            default="skip",
        )
        if answer == "quit":
            return 0
        change.decision = {"replace": "apply", "skip": "skip", "keep": "keep"}[answer]
        if answer == "skip" and change.artifact.id not in document.get("state", {}).get(
            "artifacts", {}
        ):
            change.decision = "keep"
    if not args.yes:
        if not sys.stdin.isatty():
            raise KitFlowError("Use --yes to confirm a non-interactive plan")
        if not Confirm.ask("Apply this plan?", default=False):
            console.print("Cancelled. No files were changed.")
            return 0
    apply(result, source)
    console.print("Configuration saved.", style="green")
    return 0


def main() -> int:
    try:
        return run(parser().parse_args())
    except (KitFlowError, OSError, UnicodeError) as error:
        console.print(f"Error: {error}", style="red", markup=False)
        return 2
    except KeyboardInterrupt, EOFError:
        console.print("Cancelled.")
        return 130
