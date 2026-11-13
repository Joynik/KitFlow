"""KitFlow command line entry point."""

import argparse
import difflib
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from kitflow.box_update import refresh_box
from kitflow.catalog import KitFlowError
from kitflow.check import configuration_issues
from kitflow.engine import CONFIG, apply, load_config, plan
from kitflow.settings import box_path, config_directory
from kitflow.source import load_box, read_instructions

console = Console(highlight=False)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="KitFlow — project standards over mise")
    result.add_argument("--version", "-v", action="version", version="KitFlow 0.3.0")
    result.add_argument(
        "--instruction",
        "-i",
        action="store_true",
        help="Read the usage guide in the terminal (works offline)",
    )
    result.add_argument(
        "command",
        nargs="?",
        choices=["init", "update", "status", "diff", "config", "check"],
        help="Action to perform; omit to prepare your box or review box updates",
    )
    result.epilog = """Commands:
  init    Choose or change project components and apply the plan
  update  Apply local templates to the project's saved selection
  status  List pending changes without applying them
  diff    Show proposed file differences without applying them
  config  Show the local box location without creating it
  check   Validate the box and connected project without changing files

Without a command, prepare the local box or offer to refresh an existing box.
"""
    result.formatter_class = argparse.RawDescriptionHelpFormatter
    result.add_argument(
        "--project",
        "-p",
        type=Path,
        default=Path.cwd(),
        help="Target project directory (default: current directory)",
    )
    result.add_argument(
        "--box", "-b", type=Path, help="Use another box directory for this command only"
    )
    result.add_argument("--catalog", dest="box", type=Path, help=argparse.SUPPRESS)
    result.add_argument(
        "--components",
        "-c",
        metavar="IDS",
        help="Complete component selection without the menu, e.g. python,ruff (init only)",
    )
    result.add_argument(
        "--manage",
        "-m",
        action="append",
        default=[],
        metavar="ID",
        help="Let KitFlow manage an excluded file or block again; repeat for multiple IDs (init only)",
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
    if args.instruction:
        if args.command or args.components is not None or args.manage or args.yes:
            raise KitFlowError("Use --instruction without a command or project actions")
        console.print(Markdown(read_instructions(args.box)))
        return 0
    if args.command == "check":
        if args.components is not None or args.manage or args.yes:
            raise KitFlowError("check accepts --box and --project, without project actions")
        box = args.box.resolve() if args.box else box_path()
        root = args.project.resolve()
        console.print(f"Checking box: {box}", markup=False)
        connected = (root / CONFIG).exists() or (root / CONFIG).is_symlink()
        console.print(
            f"Checking project: {root}"
            if connected
            else "Project has no kitflow.toml; project checks skipped.",
            markup=False,
        )
        issues = configuration_issues(box, root)
        for path, message in issues:
            console.print(f"{path}: {message}", style="red", markup=False)
        if issues:
            console.print(f"Check failed: {len(issues)} issue(s).", style="red")
            return 2
        console.print("Configuration checks passed.", style="green")
        return 0
    if args.command == "config":
        if args.box or args.components is not None or args.manage or args.yes:
            raise KitFlowError(
                "config displays the user configuration location; it accepts no options"
            )
        console.print(f"Configuration: {config_directory()}", markup=False)
        console.print(f"Local box: {box_path()}", markup=False)
        return 0
    if args.command is None:
        if args.components is not None or args.manage or args.yes:
            raise KitFlowError("Use init to select project components or apply a plan")
        existing = args.box is None and box_path().exists()
        catalog, _ = load_box(args.box)
        if (
            existing
            and sys.stdin.isatty()
            and Confirm.ask(
                "Download updates for the standard box? Existing differences require approval",
                default=False,
            )
        ):

            def decide(name: str, before: bytes | None, after: bytes) -> bool:
                difference = "".join(
                    difflib.unified_diff(
                        (before or b"").decode(errors="replace").splitlines(keepends=True),
                        after.decode(errors="replace").splitlines(keepends=True),
                        fromfile=f"local/{name}",
                        tofile=f"incoming/{name}",
                    )
                )
                console.print(Syntax(difference, "diff", word_wrap=True))
                return Confirm.ask(f"Apply this box file: {name}?", default=False)

            count = refresh_box(box_path(), decide)
            console.print(f"Box files updated: {count}. Personal files were preserved.")
        elif existing and not sys.stdin.isatty():
            console.print("Existing box kept. Run kitflow in a terminal to review box updates.")
        console.print(f"Box ready: {catalog.root}", markup=False)
        console.print("Edit this box to define your standards. Run kitflow init in a project.")
        return 0
    root = args.project.resolve()
    if not root.is_dir():
        raise KitFlowError(f"Project directory does not exist: {root}")
    exists = (root / CONFIG).exists()
    command = args.command
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
    catalog, source = load_box(args.box)
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
