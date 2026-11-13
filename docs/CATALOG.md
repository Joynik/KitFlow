# Catalog format

A box is a local declarative catalog stored in your KitFlow configuration directory. Adding a
component does not require application code when existing rules suffice. All conditions reference
component IDs. An empty condition applies to every project.

```text
box/
├── kitflow-box.toml       Components, conditions and output paths
├── templates/         Whole-file templates
└── tasks/             Shell fragments, without mise table headers
```

## Components

```toml
schema = 1

[[components]]
id = "python"
label = "Python"
category = "Languages"
description = "Base Python project files."
requires = []
conflicts = []

[[components]]
id = "django"
label = "Django"
category = "Frameworks"
requires = ["python"]
```

Component IDs are stable lowercase identifiers. Declaration order determines display order.
Dependencies are recursive. Unknown dependencies and dependency cycles are rejected. Conflicts are
checked against the resolved selection. Category labels and component descriptions come from the
catalog.

## Whole files

```toml
[[files]]
id = "ruff"
path = "ruff.toml"
template = "templates/ruff.toml"
when = ["python", "ruff"]
mode = "managed"
```

Every component listed in `when` must be selected. File IDs must be unique. Output paths must also
be unique. Use `mode = "once"` for files that must never be updated or deleted after creation. Files
are copied as bytes. Parameter substitution is not implemented. Nested paths and relative symbolic links are supported. Paths outside the project are rejected. `.git`, `.beads`, `.venv` and `kitflow.toml` are
reserved targets. `mise.toml` is reserved for block management.

Keep output paths stable for an existing artifact ID. A path migration requires explicitly retiring
the old artifact before adopting the new path. Empty directories and recursive directory deletion are not supported.

## Directory templates

A `template` may point to a directory. Its contents are copied recursively under `path`:

```toml
[[files]]
id = "editor-settings"
path = ".vscode"
template = "templates/vscode"
when = ["python"]
```

Hidden files and directories are included, such as `.env.example` and `.nested/settings.json`.
Each file is managed independently. Its ID combines the rule ID and relative path, for example
`editor-settings/settings.json`. Use this ID with `--manage` to restore management of an excluded
file. Keep rule IDs and output paths stable.

Updates include new files and remove unchanged managed files missing from the template. Modified
files require a conflict decision. Personal files are preserved. Empty directories are ignored;
existing directories are not deleted. Special files and absolute symbolic links are rejected. `mode = "once"`
applies separately to each file. Files are copied as bytes; executable permissions are not copied.
`kitflow check` also checks TOML and JSON files inside directory templates.

## Symbolic links

Relative symbolic links are copied as links, including links to directories. The link target text is
preserved exactly. KitFlow does not traverse links, copy their target contents or validate those
contents. A target may be missing; KitFlow preserves the link so the target can be supplied later.
Relative targets may contain `..`; the destination is interpreted from the link's new location.
Absolute link targets are rejected.

A `template` can itself be a relative link, or a directory can contain relative links. Updates compare
link target text, detect manual changes and use the usual conflict decisions. Removal deletes only
the link. KitFlow never writes through it. Output parent directories must be real directories;
KitFlow rejects paths that traverse a symbolic link.

## Composed tasks

```toml
[[tasks]]
name = "lint"
template = "tasks/python-lint.sh"
when = ["python"]

[[tasks]]
name = "lint"
template = "tasks/django-lint.sh"
when = ["django"]
```

The first fragment could contain `ruff check .`. The second fragment could contain
`python manage.py check`. KitFlow combines matching fragments into a single marked task named
`lint`. The artifact ID becomes `task.lint`. Task names allow letters, digits, underscores, hyphens
and colons. Fragments run in catalog order and stop on a failed command. Each command must work from
the project root with tools already available. Fragments must not contain a triple single quote
delimiter.

## Environment entries

```toml
[[env]]
name = "PYTHONUNBUFFERED"
value = "1"
when = ["python"]
```

Values are literal strings. Environment names must be valid shell variable names. Each entry
receives its own markers inside `[env]`. The artifact ID becomes `env.PYTHONUNBUFFERED`. Do not
place secrets in the catalog.

## Extending and checking

1. Add a component and its dependency rules to `kitflow-box.toml`.
2. Add templates and shell fragments in the catalog repository.
3. Declare the output files and task conditions.
4. Run `kitflow init --box ./box --project /tmp/example` in an empty test directory.
5. Run `kitflow diff --box ./box --project /tmp/example` after changing templates or the selection.

KitFlow downloads the example on first use. Later bare `kitflow` runs offer to review box updates.
Project commands read your local box. Edit and back up that directory directly. Project state stores
installed artifact checksums to detect local edits and obsolete files. See
[the user instructions](INSTRUCTION.md) for the setup and update workflow.

## Empty initial documents

Use a creation rule instead of an empty template file:

```toml
[[files]]
id = "project"
path = "PROJECT.md"
empty = true
mode = "once"
```

An empty file rule requires `mode = "once"` and must not specify `template`. Existing files are
preserved. Created files are never updated or deleted afterward.
