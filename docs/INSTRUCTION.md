# Using KitFlow

KitFlow copies your configuration templates into projects and keeps those files up to date. It also
builds mise tasks from the components you select. Install the required tools separately.

```text
Prepare your box → Edit your templates → Initialize a project → Preview changes → Update
```

## Prepare your box

Run this once:

```bash
kitflow
```

KitFlow downloads the standard box into `~/.config/kitflow/default/`. It does not change your
project. With `XDG_CONFIG_HOME`, use `$XDG_CONFIG_HOME/kitflow` instead.

```text
~/.config/kitflow/
├── default/             Standard box; updated by KitFlow
│   ├── kitflow-box.toml
│   ├── tasks/
│   └── templates/
├── kitflow-box.toml     Your additional or replacement definitions
├── tasks/               Your shell fragments
└── templates/           Your templates
```

Edit the files outside `default/` and keep a backup. Your files override standard files with the
same relative path. For example, copy `default/templates/ruff.toml` to `templates/ruff.toml`, then
edit the copy. The next project update uses your version. Other standard templates remain available.
Directories merge file by file, including hidden files. Delete your override to use the standard
file again. An empty override supplies an empty file.

The root `kitflow-box.toml` starts with `schema = 1`. Add definitions there. Entries with new IDs
extend the standard catalog. An existing ID replaces its entire standard entry. Task fragment IDs
are separate from mise task names: two fragments may contribute to `lint` without replacing each
other. See `docs/CATALOG.md` for the format and the optional `[disabled]` lists.

### Update the standard box

Upgrade KitFlow before updating to a newer box schema. Older binaries reject schema 3 safely.

```bash
kitflow box update
```

KitFlow downloads and validates the standard box with your overrides, then replaces `default/`
without showing differences or asking for confirmation. It also removes obsolete standard files.
User files and projects stay unchanged. A failed download or invalid configuration leaves the
existing standard box unchanged. Keep personal changes outside `default/`.

Later bare `kitflow` runs keep the box without downloading updates. Existing flat boxes continue to
work offline. Their first `kitflow box update` adds `default/` and preserves every existing file as
a user override. These overrides keep priority; remove only those you want to inherit again.

A template can also be a folder. Add a rule to `kitflow-box.toml`:

```toml
[[files]]
id = "editor-settings"
path = ".vscode"
template = "templates/vscode"
when = ["python"]
```

KitFlow copies every file inside `templates/vscode` into the project's `.vscode`, including hidden
files and nested folders. Updates manage each file separately and preserve personal files. Empty
folders are ignored. Relative symbolic links are preserved without copying or checking their target
contents. Missing targets are allowed. Absolute links are rejected. See
[the catalog reference](https://github.com/Joynik/KitFlow/blob/main/docs/CATALOG.md) for the full
format.

## Set up a project

```bash
cd /path/to/project
kitflow init
```

1. Choose languages. The Navigator shows steps on the left and the current choices on the right.
2. Follow the available steps: frameworks, application server, databases, infrastructure, build
   tools, checks, testing, migrations, translations and instructions. Inapplicable steps are hidden.
3. Use Up/Down to move and Enter or Space to toggle. Right opens the next step; Left returns. Mouse
   clicks work too. Tab reaches actions. Ctrl+S opens the selection review.
4. Select **Review files**, inspect the proposed changes and confirm. Escape cancels without writes.

```text
Languages → Frameworks → Server → Databases → Infrastructure → Tools → Review
```

Recommended tools are selected when their step opens. You can disable any recommendation.
Dependencies are added automatically. Choosing a conflicting alternative removes the previous choice
and its dependents. The project saves the resolved selection in `kitflow.toml`; keep its state
tables. A framework is optional. KitFlow creates configuration and tasks, not application source
code.

Run `kitflow init` again to edit the current selection. Ordinary interactive `kitflow update`
offers:

- **Update files**: update templates for the saved selection.
- **Change setup**: open the same wizard with the current selection to add or remove components.
- **Exit**: leave the project unchanged.

`kitflow update -y` skips the menu and wizard. It applies templates for the saved selection and
refuses unresolved conflicts. Existing project choices are preserved, including disabled
recommendations. New languages or frameworks can introduce new recommended tools.

Use Up/Down and Enter, or click an item, to choose an action. Escape cancels. Conflict actions and
plan confirmations use the same controls. When no files need updating, KitFlow reports this without
showing an empty plan or asking for confirmation.

Profiles have been replaced by wizard definitions in `kitflow-box.toml`. Existing project selections
continue working. Old local profile files are no longer read. See the catalog reference for
`[[steps]]`, visibility conditions and `recommended`.

## Run project tasks

KitFlow composes mise tasks from the selected components. The standard box provides these roles when
the corresponding tools are selected:

| Task | Purpose |
| --- | --- |
| `mise run check` | Run lint, formatting checks and type checks without applying fixes; include configured migration checks |
| `mise run lint` | Report lint problems |
| `mise run lint-fix` | Apply supported lint fixes; remaining problems still fail |
| `mise run format` | Apply formatting |
| `mise run format-check` | Report files that need formatting without rewriting them |
| `mise run typecheck` | Check types |
| `mise run test` | Run independently selected test tools |
| `mise run verify` | Run configured code checks, application checks and tests in order |
| `mise run build` | Build every selected language component |
| `mise run frontend:dev` | Start the selected frontend development script |
| `mise run frontend:run` | Start or preview the built frontend |
| `mise run backend:run` | Run a selected Rust web application |
| `mise run build-release` | Build selected native components with release optimization |
| `mise run help` | List project tasks and descriptions; also available as the default task |

`kitflow check` validates KitFlow configuration. `mise run check` checks application code and may
create ordinary tool caches or build outputs. Tests run separately. Checks stop at the first failed
command. The aggregate calls the existing mise tasks once, so their user overrides also apply.
Native tool rules still apply: for example, Clippy fixes require a clean version-controlled working
tree. KitFlow does not install tools. Django commands and djLint use the project environment through
uv; uv may synchronize the project environment before running them.

Diagnostics use short formats where supported. Warnings, errors and failing filenames remain
visible. Django HTML tasks scan only `templates/`; edit their fragments if your layout differs.
Development servers retain their address; Vite does not clear earlier terminal output.

## Configure the generated environment

KitFlow selects components. You configure the project in `mise.toml`. Initial settings are added
once and then belong to you. KitFlow preserves their values during updates and component removal.
The standard box loads optional overrides from `.env`; keep secrets there. `mise run env:local`
creates `.env` from `.env.example` without replacing an existing file.

```text
kitflow init → Edit mise vars/env → Set local .env values → Run mise tasks
```

Set `python_directory`, `javascript_directory`, `rust_directory` and `swift_directory` under
`[vars]` for the selected languages. Paths are relative to the project root; spaces are supported.
For example, set `rust_directory = "src-tauri"` for that layout. Each task fragment runs in its
configured directory. Shared `build`, `check` and `test` tasks combine selected components.

Choose test runners separately: Django, pytest, unittest, Bun, Cargo or Swift. Language selection
alone does not automatically enable a test runner. Configure unittest discovery with
`unittest_directory`; pytest and Bun use their native project settings. Swift build/type checks use
compilation.

### Python servers and migrations

Select Granian, Gunicorn or Uvicorn. Set `vars.python_app` to the application's `module:object`. Use
a compatible interface or worker: Django WSGI uses a WSGI server; FastAPI uses ASGI. The initial
FastAPI + Gunicorn settings select its native `asgi` worker, which requires a compatible Gunicorn
release. Adjust `gunicorn_worker` for other workers or older releases. Granian reload requires its
`reload` extra. Tool dependencies are installed separately in your application environment.

`mise run dev` enables reload; `mise run run` does not. Neither builds first by default. Set
`build_before_run = "true"` to run the configured build before starting. Set address and port
through `server_host_default` and `server_port_default`, or override them with `SERVER_HOST` and
`SERVER_PORT` in `.env`. Server settings are shared across the three backends. The simple Django
server remains available as `django:runserver`.

Django supplies its migration commands. Select Alembic for FastAPI or another SQLAlchemy
application; configure its migration environment and `alembic_config` in the application first.
`db:makemigrations NAME` creates a named migration; `db:migrate` applies it; `db:check` checks for
missing migrations. These are mise task names, used with `mise run`. FastAPI's `app-check` imports
the application and generates OpenAPI; it does not test application startup.

### Swift and frontend builds

Set `swift_backend` to `swiftpm` or `xcode`. Xcode also needs `xcode_project`, `xcode_scheme` and
`xcode_destination`. SwiftLint is optional and selected separately. Debug and release builds use the
configured backend; Swift tests use the same backend.

JavaScript builds run the package.json script named by `javascript_build_script` (default: `build`).
Set it to an existing script such as `css:build` when needed. Vite also supplies `frontend:dev`,
`frontend:build` and `frontend:preview`. Tauri supplies `start` and `app:build`; configure its own
frontend hooks in the application's Tauri configuration.

### Translations, databases and Docker

Select Django, Babel or package.json translations. Configure target locales in `i18n_languages`,
excluding `i18n_source_language`. `mise run translations` runs the selected tools. Babel requires
your extraction mapping file; the package.json backend uses `i18n_script`.

SQLite and PostgreSQL provide `db:backup FILE` and `db:restore FILE`. Defaults use
`database_backup_file` and `database_restore_file`. PostgreSQL uses `PGHOST`, `PGPORT`, `PGDATABASE`
and `PGUSER`; keep its password in `.pgpass` or local environment settings. SQLite uses
`database_sqlite_path`. `db:prepare` creates a new SQLite database, optionally from
`database_init_sql`, without replacing an existing database.

Backups never replace existing files. **Stop application writes before restoring.** Restore replaces
data. SQLite stages SQL in a temporary database and refuses restoration with pending WAL files.
PostgreSQL restores in a transaction and stops on SQL errors. Restore only trusted SQL files.

Docker provides `docker:build`, `docker:check`, `docker:up`, `docker:status`, `docker:logs` and
`docker:down`. Configure `compose_file` and `compose_env_file`. Container database operations use
`docker:db:backup FILE` and `docker:db:restore FILE`, or pass `--docker` to the ordinary database
task. Configure `database_docker_service` and the container's SQLite path when needed. The selected
container must be running and contain the native database client. PostgreSQL connection variables
must also be configured inside that container. SQLite restore requires a POSIX shell there.
`docker:down` keeps volumes.

## Update project files

After editing your box, run these commands in each project you want to update:

```bash
kitflow status   # List files and blocks that need changes
kitflow diff     # Show proposed content changes, not past history
kitflow update   # Review and apply the changes
```

Unchanged files from removed components are deleted after confirmation. Modified files require an
explicit decision. KitFlow does not recursively delete directories.

If a managed file was edited in the project, KitFlow shows the differences and asks:

| Answer | Result |
| --- | --- |
| `replace` | Apply the proposed update or removal |
| `skip` | Leave it unchanged for this update |
| `keep` | Leave it unchanged and stop managing it |
| `quit` | Cancel without applying changes |

At first setup, skipping an existing file also leaves it under your control. An identical file can
be adopted without replacement. Files marked `mode = "once"`, including the example README.md and
PROJECT.md, are created only if absent. KitFlow never updates or deletes them afterward.

KitFlow manages marked tasks and environment entries in `mise.toml`. Remove both markers around a
block to take control of it. Install tools yourself, then run tasks with `mise run TASK`.

## Commands and options

Run `kitflow check` after editing your box or project configuration. It checks the box and, when
present, the current project's `kitflow.toml`. It validates fields, dependencies, paths, template
availability, wizard definitions, TOML/JSON file syntax and managed mise blocks. It does not
download files, change them or run tools. Tool-specific settings and shell commands are not checked
against external tools.

```bash
kitflow check
kitflow check -b /path/to/my-box -p /path/to/project
```

Errors include a file path and explanation. Exit code 0 means the configuration is valid; 2 means
validation failed. A valid configuration may still have pending updates; use `status` or `diff` to
see those changes. If the box is missing, run `kitflow` to prepare it first.

| Command | Purpose |
| --- | --- |
| `kitflow` | Prepare the local box without changing projects |
| `kitflow box update` | Update only the standard box in `default/` |
| `kitflow init` | Choose or change project components |
| `kitflow update` | Update files or open the setup wizard |
| `kitflow status` | List pending changes |
| `kitflow diff` | Show proposed file differences |
| `kitflow config` | Show configuration paths without creating the box |
| `kitflow check` | Validate the box and connected project without changing files |
| `kitflow -i` | Read this guide in the terminal, including offline |
| `kitflow -h` | Show command help |
| `kitflow -v` | Show the installed version |

Use `--project/-p` to work on a project from another directory:

```bash
kitflow init -p /path/to/project
kitflow update -p /path/to/project
```

Use `--box/-b` to select a different box for one command. The path points to the directory
containing `kitflow-box.toml`. Repeat this option for later commands that should use that box.

```bash
kitflow init -b /path/to/my-box
kitflow update -b /path/to/my-box
```

Use `--components/-c` to supply the **complete selection** without the menu. These are component IDs
from `kitflow-box.toml`, separated by commas. Omitted components are removed from the selection.
Dependencies are added automatically. `--yes/-y` confirms a plan but never overwrites conflicts.

```bash
kitflow init -c python,ruff,ty -y
```

Use `--manage/-m` with an excluded file or block ID to let KitFlow manage it again. Find IDs in
`kitflow-box.toml`; task IDs use `task.NAME` and environment IDs use `env.NAME`. Repeat `-m` for
multiple IDs. This operation still checks conflicts and asks for confirmation.

```bash
kitflow init -m ruff
```

You can also change the component list in the project's `kitflow.toml` and run `kitflow update`.
Keep the state tables so KitFlow can detect manual edits and obsolete files. `status` and `diff`
return exit code 1 when changes are pending, 0 when current, and 2 on errors.

## Update the program

```bash
brew update
brew upgrade joynik/tap/kitflow
```

This updates KitFlow itself. It does not replace your box or update project files. Your own
`INSTRUCTION.md` takes precedence when you run `kitflow -i`.
