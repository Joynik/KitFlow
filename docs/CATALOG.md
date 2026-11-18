# Catalog format

A box describes which files and mise entries to generate for a project's components.

```text
kitflow-box.toml   Components, wizard steps and rules
settings/          Initial mise settings
templates/         Files, directories and text fragments
tasks/             Shell fragments
```

## Layers and schema

The user box root overlays `default/`. Use `schema = 4` for new catalogs. KitFlow reads schemas 1–3
and warns on older user schemas during updates. Migrate them by hand. Upgrade KitFlow before
downloading a standard box that requires a newer schema or catalog feature.

- Sections `components`, `steps`, `files`, `tasks`, `defaults` and `env` merge by ID. A replacement
  takes the original position and replaces the entire entry. New IDs append. IDs must be unique
  within a section and layer. Legacy task IDs use the template stem; legacy env IDs use `name`.
- A user template overrides the same relative path in `default/`. Directories merge file by file. An
  empty override supplies an empty file. Remove an override to restore the standard version.
- To omit a standard entry, list its ID under `[disabled]` in the corresponding section. For
  example, `tasks = ["ruff-lint"]`. Unknown or duplicate IDs fail validation. Fix references to
  disabled components. Disabling a directory rule also disables its children.

## Components and wizard steps

```toml
schema = 4

[[components]]
id = "quality"
label = "Quality checks"
category = "Checks"
description = "Check Python code."
requires = ["python"]
recommended = true

[[steps]]
id = "checks"
label = "Checks and formatting"
categories = ["Checks"]
order = 60
description = "Choose the checks to run."
```

Use stable lowercase component IDs. Components appear in declaration order. `requires` adds
dependencies recursively. Unknown dependencies and cycles fail validation. `conflicts` applies to
the resolved selection. In the wizard, choosing a conflicting alternative removes the previous
selection and its dependents.

| Condition | Matches when |
| --- | --- |
| `when` | All listed components are selected |
| `when_any` | At least one listed component is selected, or the list is empty |
| `when_not` | None are selected. Available on file and task rules |

Conditions combine. All IDs must exist. `when` and `when_any` apply to steps, components and
artifact rules. A component without visibility conditions appears when its dependencies are
selected. Explicit conditions can show it sooner; selecting it still adds its dependencies.

`recommended = true` selects an eligible option when its step first opens, without replacing
conflicts. Deselections and existing project choices are preserved. Steps sort by `order`, then
declaration order. A category belongs to one step at most. Unassigned categories get automatic
steps. Empty steps are hidden. KitFlow reserves `review` and `ownership`.

## File rules

```toml
[[files]]
id = "editor-settings"
path = ".vscode"
template = "templates/vscode"
when = ["python"]
mode = "managed"
```

Use exactly one source: `template`, `fragments` or `empty = true`. File IDs and output paths must be
unique. Keep paths stable for each ID. Retire the old artifact before changing its path. Paths must
stay within the project. `.git`, `.beads`, `.venv` and `kitflow.toml` are reserved. KitFlow manages
`mise.toml` through mise rules. It copies bytes without substitution or executable permissions.

| Mode | Behavior |
| --- | --- |
| `managed` (default) | Replace a whole file, with conflict review for local edits |
| `once` | Create when absent. Ordinary updates never replace or delete it. Required for `empty = true` |
| `block` | Replace only a marked region. Requires UTF-8 text or fragments |

A directory template includes nested and hidden files. Each child has its own ID, such as
`editor-settings/settings.json`. Use this ID with `init -m`. Updates add new children and remove
obsolete unchanged ones. They preserve personal files and review modified files. Empty folders are
ignored. Directories are never deleted. `once` applies per child. Special files are rejected.

Relative links, including dangling links and targets containing `..`, are copied as link text.
KitFlow compares the text during updates and removes only the link. It never reads or writes the
target through the link. Absolute links and output paths through symlink parents are rejected.

### Blocks and composed text

For `mode = "block"`, keep ownership markers out of templates. KitFlow adds a `# <kitflow>` /
`# </kitflow>` pair and a separate user block on creation. Ordinary updates replace the marked
region automatically, without conflict prompts or diff output. Surrounding bytes stay intact.
Removing the rule removes only the marked block. Missing or invalid markers leave the file untouched
and excluded. To opt in, add a valid pair around the managed rules, then run
`kitflow init -m FILE_ID` if excluded.

```toml
[[files]]
id = "ignore"
path = ".gitignore"
mode = "block"
fragments = [
  { template = "templates/gitignore/general.txt" },
  { template = "templates/gitignore/python.txt", when = ["python"] },
]
```

Fragments are regular UTF-8 files. Both the file and fragment conditions must match. A fragment
accepts `template`, `when` and `when_any`. KitFlow trims edge line breaks, joins nonempty parts with
one blank line and adds a final newline. Put section comments in the fragments. The assembled file
has one artifact ID and checksum. Removing a component removes its parts at the next update.

Use `format = "dotenv"` for environment examples. Active duplicate names, including `export`
assignments, fail validation. Comments do not count. `kitflow check` checks compatible fragment
combinations. Keep common names in a shared fragment and actual secrets in the local `.env`. The
standard box uses block management for ignore files and whole-file management for `.env.example`.
Docker enables `.dockerignore`, and VS Code Extension enables `.vscodeignore`.

## Mise rules

```toml
[[tasks]]
id = "python-test"
name = "test"
template = "tasks/python-test.sh"
when = ["python"]
directory_env = "PROJECT_ROOT"
description = "Run selected test runners"

[[defaults]]
id = "python"
template = "settings/python.toml"
when = ["python"]

[[env]]
id = "PYTHONUNBUFFERED"
name = "PYTHONUNBUFFERED"
value = "1"
when = ["python"]
```

- **Tasks.** Matching fragments with the same `name` form one marked task, such as `task.test`.
  Names allow letters, digits, underscores, hyphens and colons. Fragments run in catalog order and
  stop on failure. Use shell commands without table headers or triple single quotes. Run from the
  project root by default. `directory_env` names an exported path and isolates the directory change
  in a subshell. Paths with spaces work. Missing or invalid directories fail.
- **Metadata.** `description`, `alias` and `usage` are strings; `hide` and `quiet` are booleans.
  Fragments of the same task must agree where they declare metadata. For example,
  `usage = 'arg "[name]" help="Migration name"'` exposes `usage_name` to the shell.
- **Defaults.** Template TOML may contain only `vars`, `env` and `settings`. Each rule seeds missing
  keys once. KitFlow records the keys it adds in `kitflow.toml`. Changing values does not change
  ownership. Deselecting a component removes its tracked keys unless another selected component
  still needs them. Pre-existing and untracked keys stay intact. The standard box gives `.env`
  overrides priority.
- **Environment.** Use shell variable names and literal string values. Each entry has its own
  markers in `[env]` and an artifact ID such as `env.PYTHONUNBUFFERED`.

## Check your box

Create an empty test directory, run `kitflow check -b ./box -p /tmp/example`, then try
`kitflow init -b ./box -p /tmp/example`. After editing a template, run
`kitflow diff -b ./box -p /tmp/example`. Checks validate TOML and JSON templates, including files in
directory templates. They do not download, write or execute tasks. See
[INSTRUCTION.md](INSTRUCTION.md) for project usage and ownership rules.
