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
are copied as bytes. Parameter substitution is not implemented. Nested paths are supported. Symbolic
links and paths outside the project are rejected. `.git`, `.beads`, `.venv` and `kitflow.toml` are
reserved targets. `mise.toml` is reserved for block management.

Keep output paths stable for an existing artifact ID. A path migration requires explicitly retiring
the old artifact before adopting the new path. Directory trees can be represented by individual file
entries. Empty directories and recursive directory deletion are not supported.

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
