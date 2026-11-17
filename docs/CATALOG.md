# Catalog format

A box is a local declarative catalog stored in your KitFlow configuration directory. Adding a
component does not require application code when existing rules suffice. All conditions reference
component IDs. An empty condition applies to every project.

```text
box/
├── kitflow-box.toml       Components, conditions and output paths
├── settings/          Creation-only mise defaults
├── templates/         File, directory and text fragment templates
└── tasks/             Shell fragments, without mise table headers
```

## Standard and user layers

The configuration directory contains the standard box in `default/` and user definitions at its
root. The standard box uses `schema = 4` for conditional file fragments. KitFlow still reads legacy
schema 1, 2 and 3 boxes; a user overlay may contain only a schema declaration. Older KitFlow
versions reject the new standard schema instead of silently generating incomplete tasks.

New user catalogs use the current schema (4). Update commands warn if your user catalog declares an
older supported schema. Review this reference and update the declaration manually; KitFlow never
rewrites the schema of an existing user catalog.

KitFlow merges `components`, `files`, `tasks`, `env`, `defaults` and `steps` by stable `id`. A user
entry replaces the whole standard entry; omitted fields do not inherit values. New IDs append
entries. Replacements keep their standard position. The effective catalog must have valid
dependencies and conditions.

Templates use relative paths as their identity. User files replace standard files at the same path.
Directories merge file by file. An empty file is an explicit override. Removing an override restores
the standard definition or file.

Use explicit IDs for task fragments and environment entries. Legacy tasks without `id` use the
template filename stem; legacy environment entries use their `name`. Duplicate IDs within one
section and layer are errors. The same ID may exist in different sections.

Disable entries without supplying replacements:

```toml
schema = 1

[disabled]
components = []
files = ["tools"]
tasks = ["ruff-lint"]
env = []
defaults = []
steps = []
```

Lists contain IDs from the corresponding merged section. Unknown or duplicate IDs are errors.
Disabling a component also requires updating or disabling entries that reference it. Disabling a
file rule disables all its directory-template children.

`kitflow box update` validates the incoming standard box and its combination with user definitions
before replacing `default/`. `kitflow check` reads the local layers and checks their combined
configuration without downloading, writing files or running tasks.

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

## Navigator wizard

Define ordered steps in the same catalog. Each category belongs to at most one step:

```toml
schema = 3

[[steps]]
id = "checks"
label = "Checks and formatting"
categories = ["Checks"]
order = 60
description = "Disable any recommendation you do not need."

[[components]]
id = "quality"
label = "Quality checks"
category = "Checks"
recommended = true
requires = ["python"]
```

Steps merge by ID, just like components. `order` sorts them; declaration order breaks ties.
Unassigned categories receive automatic steps, including in legacy boxes. Empty steps are hidden.
The final review and user-owned-file steps are supplied by KitFlow. Their IDs `review` and
`ownership` are reserved.

A component is available when its required components are selected. To show an option before all its
dependencies are selected, supply `when` and/or `when_any`. They control wizard visibility;
selecting the option still adds every mandatory `requires` dependency. For example, a web framework
can use `when_any = ["javascript", "typescript"]` and require its UI library. The wizard adds that
library automatically. `when` requires every listed ID; `when_any` requires at least one. Both
conditions apply when both are present. These conditions may also hide whole steps.

`recommended = true` selects a newly available option when its step opens. Recommendations never
replace conflicting choices. Users can deselect them; returning to a step does not select them
again. Existing projects keep their saved selection. Selecting a conflicting alternative removes the
previous alternative and dependent components, with a notification.

The wizard supports multiple languages and a project without a framework. It does not create
application source code or install dependencies. Profiles and `--profile/-r` have been removed.
Existing projects already store resolved components, so they need no selection migration. Old local
profile files remain on disk but are no longer read.

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
are copied as bytes. Parameter substitution is not implemented. Nested paths and relative symbolic
links are supported. Paths outside the project are rejected. `.git`, `.beads`, `.venv` and
`kitflow.toml` are reserved targets. `mise.toml` is reserved for block management.

Keep output paths stable for an existing artifact ID. A path migration requires explicitly retiring
the old artifact before adopting the new path. Empty directories and recursive directory deletion
are not supported.

## Directory templates

A `template` may point to a directory. Its contents are copied recursively under `path`:

```toml
[[files]]
id = "editor-settings"
path = ".vscode"
template = "templates/vscode"
when = ["python"]
```

Hidden files and directories are included, such as `.env.example` and `.nested/settings.json`. Each
file is managed independently. Its ID combines the rule ID and relative path, for example
`editor-settings/settings.json`. Use this ID with `--manage` to restore management of an excluded
file. Keep rule IDs and output paths stable.

Updates include new files and remove unchanged managed files missing from the template. Modified
files require a conflict decision. Personal files are preserved. Empty directories are ignored;
existing directories are not deleted. Special files and absolute symbolic links are rejected.
`mode = "once"` applies separately to each file. Files are copied as bytes; executable permissions
are not copied. `kitflow check` also checks TOML and JSON files inside directory templates.

## Symbolic links

Relative symbolic links are copied as links, including links to directories. The link target text is
preserved exactly. KitFlow does not traverse links, copy their target contents or validate those
contents. A target may be missing; KitFlow preserves the link so the target can be supplied later.
Relative targets may contain `..`; the destination is interpreted from the link's new location.
Absolute link targets are rejected.

A `template` can itself be a relative link, or a directory can contain relative links. Updates
compare link target text, detect manual changes and use the usual conflict decisions. Removal
deletes only the link. KitFlow never writes through it. Output parent directories must be real
directories; KitFlow rejects paths that traverse a symbolic link.

## Composed tasks

```toml
[[tasks]]
id = "python-lint"
name = "lint"
template = "tasks/python-lint.sh"
when = ["python"]

[[tasks]]
id = "django-lint"
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

## Task metadata and working directories

Task fragments may define `description`, `alias`, `usage`, `hide` and `quiet`. String fields use
mise's native meanings; `hide` and `quiet` are booleans. Metadata declared by multiple fragments of
one task must agree. Shell fragments still compose in catalog order.

```toml
[[tasks]]
id = "application-test"
name = "test"
template = "tasks/application-test.sh"
when = ["python"]
directory_env = "PROJECT_PYTHON_DIRECTORY"
description = "Run selected test runners"
```

`directory_env` names an exported variable containing the fragment's working directory. KitFlow
wraps that fragment in a subshell, so other fragments keep their own directories. Missing values and
invalid directories fail explicitly. Paths with spaces are supported. The core contains no
language-specific path guessing.

`usage` declares native mise arguments, available as `usage_name`, `usage_file` and other variables
inside the fragment. For example: `usage = 'arg "[name]" help="Migration name"'`.

All artifact sections support `when` and `when_any`. Every ID in `when` must be selected. At least
one ID in a nonempty `when_any` must be selected. Both conditions apply when both are present.

## Initial user settings

```toml
[[defaults]]
id = "python"
template = "settings/python.toml"
when = ["python"]
```

A defaults template is TOML containing only `[vars]`, `[env]` and `[settings]`. KitFlow adds missing
keys to `mise.toml` without replacing existing values or comments. It records the seed once. Later
updates and component removal do not alter or remove these settings, even if a user deletes a key.
Newly selected defaults entries may supply additional missing keys. Defaults have no management
markers; they become user-owned immediately. Do not put secrets in defaults templates.

The standard box loads `.env` and uses `env.NAME | default(value=vars.name)` for fallbacks. Values
from `.env` therefore take priority over initial variable values. Runtime configuration belongs in
mise, not in the project's `kitflow.toml`. After changing project paths, update the corresponding
mise variables; no KitFlow reconfiguration is needed.

## Environment entries

```toml
[[env]]
id = "PYTHONUNBUFFERED"
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

KitFlow downloads the standard example into `default/` on first use. Run `kitflow box update` to
replace that standard snapshot explicitly. User overrides remain outside `default/`. Project
commands read your local box. Edit and back up that directory directly. Project state stores
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

## Composed text files

Use `fragments` instead of `template` to assemble one UTF-8 file from ordered parts:

```toml
[[files]]
id = "ignore"
path = ".gitignore"
mode = "managed"
fragments = [
  { template = "templates/gitignore/general.txt" },
  { template = "templates/gitignore/python.txt", when = ["python"] },
  { template = "templates/gitignore/web.txt", when_any = ["javascript", "typescript"] },
]
```

A file rule accepts exactly one source: `template`, `fragments` or `empty`. A fragment accepts
`template`, `when` and `when_any`. Both file and fragment conditions must match. Paths use the same
user-over-standard lookup as other templates. Fragments must be regular UTF-8 files, not folders or
symbolic links. Leading and trailing line breaks are removed from each part; nonempty parts are
joined with one blank line, followed by a final newline. Other whitespace and comments are
preserved.

Put section comments inside the fragments. The final file has one artifact ID and checksum. Updates
replace the whole generated file after the usual conflict review; they do not merge local edits into
individual parts. Removing a component removes its parts on the next project update.

For environment examples, set `format = "dotenv"`. Duplicate assignment names, including `export`
assignments, are rejected when their fragments are selected together. `kitflow check` also checks
compatible fragment combinations. Commented examples do not count as assignments. Put shared
variables in one general fragment. Keep actual secrets in the user-owned `.env`.

The standard `.gitignore` and `.env.example` always exist. `.dockerignore` requires the Docker
component. All three use only matching fragments; `.env.example` is managed, while `.env` remains
user-owned. Upgrade KitFlow before downloading schema 4 standard boxes.
