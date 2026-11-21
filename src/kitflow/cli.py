"""KitFlow command line entry point."""

import argparse
import difflib
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table

from kitflow.box_layout import validate_box_links
from kitflow.box_migrations import plan_migrations, require_supported_migration
from kitflow.box_update import refresh_box
from kitflow.catalog import CURRENT_SCHEMA, Catalog, KitFlowError
from kitflow.check import configuration_issues
from kitflow.engine import CONFIG, apply, parse_config, plan, read_file
from kitflow.settings import box_path, config_directory
from kitflow.source import load_box, read_instructions

console = Console(highlight=False)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="KitFlow — project standards over mise", add_help=False
    )
    result.add_argument("--help", "-h", action="help", help="show this help message and exit")
    result.add_argument("--version", "-v", action="version", version="KitFlow 0.21.0")
    result.add_argument(
        "--instruction",
        "-i",
        action="store_true",
        help="Read the usage guide in the terminal (works offline)",
    )
    result.add_argument(
        "command",
        nargs="?",
        choices=["init", "update", "status", "diff", "config", "check", "upgrade", "show"],
        help="Action to perform; omit to prepare your local box",
    )
    result.add_argument("show_kind", nargs="?", metavar="KIND", help=argparse.SUPPRESS)
    result.add_argument("show_target", nargs="?", metavar="TARGET", help=argparse.SUPPRESS)
    result.epilog = """Commands:
  init    Choose or change project components and apply the plan
  update  Update project files, review individual changes, or change the project setup
  status  List pending changes without applying them
  diff    Show proposed file differences without applying them
  config  Show the local box location without creating it
  check   Validate the box and connected project without changing files
  upgrade Download and replace only the standard box in standard/
  show    Print generated content: show task NAME, show file PATH, show defaults
          List available names with show tasks, show files or show components

Without a command, prepare the local box. User overrides stay in its root directory.
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
        help="Complete component selection for init or show, e.g. python,ruff",
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


def choose_action(title: str, options: list[tuple[str, str]], default: str) -> str | None:
    from kitflow.tui import ActionMenu

    return ActionMenu(title, options, default).run()


def warn_box_schema(root: Path):
    from kitflow.layers import read_data

    schema = read_data(root)["schema"]
    if schema != CURRENT_SCHEMA:
        console.print(
            f"Warning: {root / 'kitflow-box.toml'} uses schema {schema}; "
            f"this KitFlow version uses schema {CURRENT_SCHEMA}. "
            "Review the catalog format and update the schema manually. "
            "The user catalog was not modified.",
            style="yellow",
            markup=False,
        )


def show_diff(change):
    if change.artifact.kind == "block":
        return

    def lines(content):
        text = (
            f"symlink -> {content}\n"
            if isinstance(content, str)
            else (content or b"").decode(errors="replace")
        )
        return text.splitlines(keepends=True)

    before = lines(change.before)
    after = lines(change.after)
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
    if not result.changes:
        console.print("No files need updating.")
        return
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


def run(args: argparse.Namespace) -> int:
    if args.command == "show":
        from kitflow.preview import preview

        if args.instruction or args.manage or args.yes:
            raise KitFlowError("show accepts --box, --project and --components")
        root = args.project.resolve()
        box = args.box.resolve() if args.box else box_path()
        content = preview(root, box, args.components, args.show_kind, args.show_target)
        sys.stdout.buffer.write(content)
        return 0
    if args.show_kind is not None:
        raise KitFlowError("Extra arguments are only supported by show")
    if args.command == "upgrade":
        if args.instruction or args.components is not None or args.manage:
            raise KitFlowError("upgrade does not accept project actions")
        destination = args.box.absolute() if args.box else box_path()

        count = refresh_box(destination, lambda *_: True)
        catalog = Catalog(destination)
        warn_box_schema(catalog.root)
        console.print(f"Standard Box version: {catalog.version}")
        console.print(
            f"Standard box files changed: {count}. User overrides and projects were preserved."
        )
        return 0
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
        catalog, _ = load_box(args.box)
        console.print(f"Box ready: {catalog.root} (version {catalog.version})", markup=False)
        console.print("Run kitflow upgrade to refresh standard/. Run kitflow init in a project.")
        return 0
    root = args.project.resolve()
    if not root.is_dir():
        raise KitFlowError(f"Project directory does not exist: {root}")
    config_snapshot = read_file(root / CONFIG)
    exists = config_snapshot is not None
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
    document = parse_config(root, config_snapshot)
    catalog, source = load_box(args.box, check_links=command == "update")
    if command in {"init", "update"}:
        require_supported_migration(catalog.required_migration)
    applied_version = document.get("box_version", 0)
    cancelled = "Cancelled. No files were changed."
    if command == "update":
        warn_box_schema(catalog.root)
        if catalog.version and catalog.version < applied_version:
            raise KitFlowError(f"Project uses Box {applied_version}; refresh the local Box first")
        previous = document.get("migrated_box_version", 0)
        migration = plan_migrations(root, document, config_snapshot, catalog.required_migration)
        if migration is not None:
            target = migration.document["migrated_box_version"]
            console.print(f"Box migration: {previous} → {target}")
            if migration.changes:
                show_plan(migration)
            if not args.yes:
                if not sys.stdin.isatty():
                    raise KitFlowError("Use --yes to confirm a non-interactive Box migration")
                if (
                    choose_action(
                        "Apply Box migration?",
                        [("apply", "Apply migration"), ("cancel", "Cancel")],
                        "cancel",
                    )
                    != "apply"
                ):
                    console.print("Cancelled. No files were changed.")
                    return 0
            validate_box_links(args.box or box_path())
            apply(migration, source)
            config_snapshot = read_file(root / CONFIG)
            document = parse_config(root, config_snapshot)
            console.print("Box migration applied.")
            cancelled = "Update cancelled. The Box migration remains applied."
        if catalog.version > applied_version:
            console.print(f"Project Box: {applied_version} → {catalog.version}")
    action = "files"
    if command == "update" and not args.yes and sys.stdin.isatty():
        action = choose_action(
            "What would you like to do?",
            [
                (
                    "files",
                    f"Update files to Box {catalog.version}"
                    if catalog.version > applied_version
                    else "Update files",
                ),
                ("review", "Review and update files"),
                ("setup", "Change setup"),
                ("exit", "Exit"),
            ],
            "files",
        )
        if action in (None, "exit"):
            console.print(cancelled)
            return 0
    if action == "review":
        from kitflow.reset import reset_files, select_reset
        from kitflow.tui import ResetFiles

        result = plan(
            root,
            catalog,
            document["selection"]["components"],
            document,
            reset=True,
            config_snapshot=config_snapshot,
        )
        candidates = reset_files(result)
        if not candidates:
            console.print("No file changes to review.")
            return 0
        selected_files = ResetFiles(candidates).run()
        if not selected_files:
            console.print(cancelled)
            return 0
        select_reset(result, candidates, selected_files)
        if command == "update":
            validate_box_links(args.box or box_path())
        apply(result, source)
        console.print(f"Files updated: {len(selected_files)}.")
        return 0
    selection = document["selection"]
    selected = list(selection.get("components", []))
    excluded = list(selection.get("excluded", []))
    if args.manage:
        unknown = set(args.manage) - set(excluded)
        if unknown:
            raise KitFlowError(f"Not excluded: {', '.join(sorted(unknown))}")
        excluded = [x for x in excluded if x not in args.manage]
    configure = command == "init" and args.components is None and not args.manage
    configure = configure or action == "setup"
    if command == "init" and args.components is not None:
        selected = [x.strip() for x in args.components.split(",") if x.strip()]
    if configure:
        from kitflow.tui import Configurator

        chosen = Configurator(catalog, selected, excluded, existing=exists).run()
        if chosen is None:
            console.print(cancelled)
            return 0
        selected, excluded = chosen.components, chosen.excluded
    selection["excluded"] = excluded
    result = plan(root, catalog, selected, document, config_snapshot=config_snapshot)
    if catalog.version and command == "update":
        result.box_version = catalog.version
    console.print(f"Project: {root}", markup=False)
    console.print(f"Box: {catalog.root}", markup=False)
    show_plan(result)
    if command == "diff":
        for change in result.changes:
            show_diff(change)
        return 1 if result.changes else 0
    if command == "status":
        return 1 if result.changes else 0
    if command == "update" and not configure and not result.changes:
        validate_box_links(args.box or box_path())
        apply(result, source)
        return 0
    for change in result.changes:
        if not change.conflict:
            continue
        show_diff(change)
        if args.yes or not sys.stdin.isatty():
            console.print("Conflicts remain. Run interactively; no files were changed.")
            return 2
        answer = choose_action(
            f"Resolve conflict: {change.artifact.path}",
            [
                ("replace", "Replace with box version"),
                ("skip", "Skip this update"),
                ("keep", "Keep as user-owned"),
                ("quit", "Exit without changes"),
            ],
            "skip",
        )
        if answer in (None, "quit"):
            return 0
        change.decision = {"replace": "apply", "skip": "skip", "keep": "keep"}[answer]
        if answer == "skip" and change.artifact.id not in document.get("state", {}).get(
            "artifacts", {}
        ):
            change.decision = "keep"
    if not args.yes:
        if not sys.stdin.isatty():
            raise KitFlowError("Use --yes to confirm a non-interactive plan")
        if (
            choose_action(
                "Apply this plan?", [("apply", "Apply plan"), ("cancel", "Cancel")], "cancel"
            )
            != "apply"
        ):
            console.print(cancelled)
            return 0
    if command == "update":
        validate_box_links(args.box or box_path())
    apply(result, source)
    console.print("Configuration saved.", style="green")
    return 0


def main() -> int:
    try:
        return run(parser().parse_intermixed_args())
    except (KitFlowError, OSError, UnicodeError) as error:
        console.print(f"Error: {error}", style="red", markup=False)
        return 2
    except KeyboardInterrupt, EOFError:
        console.print("Cancelled.")
        return 130
