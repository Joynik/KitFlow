# Using KitFlow

KitFlow generates project configuration and composes tasks for mise. Install the tools separately.

```text
Prepare the box → Choose project components → Configure mise → Run tasks → Review updates
```

## Box setup

Run `kitflow` once. It downloads the standard box to `~/.config/kitflow/default/` and creates a user
box alongside it. With `XDG_CONFIG_HOME` set, KitFlow uses `$XDG_CONFIG_HOME/kitflow` instead.

Edit and back up the user box. For example, copy `default/templates/ruff.toml` to
`templates/ruff.toml` at the box root and edit the copy. Use the root `kitflow-box.toml` to add,
replace or disable rules. See the
[catalog reference](https://github.com/Joynik/KitFlow/blob/main/docs/CATALOG.md).

`kitflow box update` downloads and validates a new standard box with your overrides. It replaces
`default/` and removes obsolete standard files without a prompt or diff. A failed update leaves the
old box intact. User files and projects stay unchanged. Later bare `kitflow` runs use your local
box. Legacy flat boxes work offline; their first box update keeps their existing files as overrides.

## Project setup and updates

Run `kitflow init` in the project. Choose one or more languages, then the applicable frameworks,
platforms and tools. A framework is optional. The wizard adds required dependencies, selects
recommendations when their steps open and lets you deselect them. Existing selections keep earlier
deselections; new choices can introduce recommendations.

- Use Up/Down to move and Enter/Space to toggle. Right advances; Left returns. Mouse clicks work.
- Tab reaches actions. Ctrl+S opens the selection review. Choose **Review files** to inspect and
  confirm the plan. Escape cancels.
- KitFlow saves resolved components and ownership checksums in `kitflow.toml`. Keep its state
  tables. Edit the selection with `init`, **Change setup**, or by editing the component list and
  running `update`. Existing selections work after the removal of profiles; old profile files are
  ignored.

`kitflow update` offers:

| Action | Result |
| --- | --- |
| **Update files** | Apply box changes for the saved selection. Show a plan when there are changes |
| **Review and update files** | Compare versions and choose individual changes or whole files |
| **Change setup** | Open the wizard with the current selection |
| **Exit** | Leave the project unchanged |

In **Review and update files**, all boxes start unchecked. Creation-only files are marked.

1. Use Enter or Right to review a file. Use Space on the file list to select the whole file.
2. Move through edits with Up/Down. Compare current and proposed content side by side, or stacked in
   a narrow terminal. Use Space or Enter to select an edit; Left returns to files.
3. Choose **Apply selected** to confirm. Escape cancels. KitFlow validates the resulting TOML and
   checks that files still match the version you reviewed.

Text files offer groups of changed lines. Binary files and links are selected as whole entries. For
`mise.toml`, select a managed task, environment entry or box-defined setting. Detached tasks and
settings outside the box defaults are preserved. Skipped changes can be reviewed later.

### Ownership and conflicts

Ordinary updates delete unchanged files from removed components after confirmation. Modified files
require a decision. Choose **Replace** to accept the proposed write or removal, **Skip** to defer,
**Keep as user-owned** to stop management, or **Exit** to cancel. During initial setup, identical
files are adopted and skipping an untracked file leaves it user-owned.

- **Creation-only files** such as `README.md`, `PROJECT.md` and `pyproject.toml` are created when
  absent. Ordinary updates preserve them.
- **Ignore files** (`.gitignore`, `.dockerignore`, `.vscodeignore`) update only inside `# <kitflow>`
  / `# </kitflow>`. Put personal rules inside `# <user>` / `# </user>`. Missing or damaged KitFlow
  markers leave the file untouched. To opt in an existing file, add an empty KitFlow block above
  your rules, then restore management with `init -m` if excluded. If an existing extension manifest
  has a `files` list, remove it before packaging with `.vscodeignore`. Move any packaging rules you
  still need into the user block.
- **`mise.toml`** uses marked tasks and environment entries. Remove both markers to take ownership
  of an entry. Ordinary updates preserve vars, env and settings. Deselecting a component removes
  keys KitFlow added for it, even after edits, unless another selected component needs them. Keys
  added by older KitFlow versions without ownership records stay in place.
- **`.env`** stays user-owned. `mise run env:local` creates it from `.env.example` when absent. Edit
  generated ignore and env fragments in your box under `templates/gitignore/`,
  `templates/dockerignore/`, `templates/vscodeignore/` or `templates/env/`.

## Run and configure mise tasks

Run `mise run help` to list the tasks your project actually has. Shared tasks combine fragments from
the selected components.

| Task | Purpose |
| --- | --- |
| `check` | Run lint, format, type and configured migration or schema checks without fixes |
| `lint`, `lint-fix` | Report lint problems or apply supported fixes |
| `format-check`, `format` | Check formatting or rewrite files |
| `typecheck`, `test` | Check types or run selected test runners |
| `verify` | Run configured checks, application checks and tests in order |
| `build`, `build-release` | Build selected components or optimized native output |
| `frontend:dev`, `frontend:run`, `backend:run` | Start the selected application or preview |

Run a task as `mise run TASK`. Checks stop on failure and may write normal tool caches or outputs.
Aggregate checks call the existing tasks, including user overrides. Tool prerequisites still apply:
Clippy fixes require a clean working tree. Django and djLint use uv, which may sync the environment.
djLint scans `templates/` by default. Initial `[settings]` sets `task.quiet = true` to hide command
echoes while keeping tool output. Add it manually to an older project if desired.

Change runtime defaults in `mise.toml` and keep secrets or local overrides in `.env`. User settings
are seeded once. For nested apps, set `javascript_directory`, `rust_directory` or `swift_directory`
under `[vars]` relative to the project root, for example `rust_directory = "src-tauri"`.

### Python paths and builds

```toml
[vars]
project_root = "."
python_source = "src"
python_tests = "tests"
```

`project_root` is relative to `mise.toml` and sets the Python directory for tests and builds.
`python_source` and `python_tests` are relative to that root. All three accept absolute paths. Use
`PROJECT_ROOT`, `PYTHON_SOURCE` or `PYTHON_TESTS` for environment overrides. Rename legacy vars
manually. Choose test runners separately from languages.

**Python package** uses `uv build` and requires a build backend in `pyproject.toml`.
**Nuitka standalone** needs Nuitka in the project environment and a C compiler. It uses
`uv run --no-sync`. Set `python_entrypoint` (default `main.py`) and `python_build_directory`
(default `dist`) relative to `project_root`. Set application-specific compilation options in the
entry point. Leave both build options unchecked to omit Python builds.

### Application servers and builds

- **Python servers.** Choose Granian, Gunicorn or Uvicorn. Set `python_app` to `module:object`. Use
  a worker or interface compatible with WSGI or ASGI. FastAPI with Gunicorn defaults to the native
  `asgi` worker; adjust `gunicorn_worker` for other releases or workers. Granian reload needs its
  `reload` extra.
- **Run modes.** `dev` enables reload; `run` does not. Set `build_before_run = "true"` to build
  first. Use `server_host_default` and `server_port_default`, or override them with `SERVER_HOST`
  and `SERVER_PORT`. Django also has `django:runserver`. FastAPI's `app-check` imports the app and
  generates OpenAPI; application startup is separate.
- **Migrations.** Django supplies its own tasks. For SQLAlchemy, select Alembic and configure its
  environment and `alembic_config`. Use `db:makemigrations NAME`, `db:migrate` and `db:check`.
- **Frontend.** Set `javascript_build_script` to a package script (default `build`). Vite keeps
  earlier terminal output and adds `frontend:build` and `frontend:preview`. Tauri adds `start` and
  `app:build`; configure its frontend hooks in the Tauri configuration.
- **Swift.** Set `swift_backend` to `swiftpm` or `xcode`. Xcode needs `xcode_project`,
  `xcode_scheme`, and `xcode_destination`. Build and test use the chosen backend. SwiftLint is
  optional.
- **Translations.** Set target locales in `i18n_languages`, excluding `i18n_source_language`. Run
  `mise run translations`. Babel needs an extraction mapping; package scripts use `i18n_script`.

Django and FastAPI applications must read their framework environment examples explicitly. For
Flask, use `app.config.from_prefixed_env()` or an equivalent loader. Uncomment examples you intend
to use.

### Databases and Docker

Use `db:backup FILE` and `db:restore FILE` for SQLite or PostgreSQL. Defaults are
`database_backup_file` and `database_restore_file`. Backups refuse to overwrite existing files.
**Stop application writes before restoring and use trusted SQL.** Restore replaces data. SQLite
stages restores in a temporary database and refuses pending WAL files. PostgreSQL restores in a
transaction.

- **SQLite.** Set `sqlite_database_path` or override it with `SQLITE_DATABASE_PATH` in `.env`. Use
  an absolute path or a path relative to the project root. `db:prepare` creates a new database
  without overwriting an existing one. `SQLITE_INIT_SQL` supplies initial SQL for this task.
- **PostgreSQL.** Set `PGHOST`, `PGPORT`, `PGDATABASE` and `PGUSER`. Keep passwords in `.pgpass` or
  local environment settings.
- **Docker.** Set `compose_file` and `compose_env_file`. Tasks include `docker:build`,
  `docker:check`, `docker:up`, `docker:status`, `docker:logs` and `docker:down`. Down preserves
  volumes. Use `docker:db:backup FILE`, `docker:db:restore FILE`, or `--docker` on the ordinary
  database task. `DATABASE_EXECUTION_MODE` selects `native` or `docker`. Set
  `database_docker_service` and, for SQLite, `SQLITE_CONTAINER_PATH`. The running container needs
  the database client and its connection settings. SQLite restore also needs a POSIX shell in the
  container.

**Prisma ORM** is available under **Data access** with JavaScript/TypeScript and PostgreSQL or
SQLite. Install Prisma 7 and its runtime dependencies separately. Tasks use `bunx --no-install`.
Edit the creation-only `prisma.config.ts` and `prisma/schema.prisma`, and set `DATABASE_URL` in
`.env`. Keep it consistent with SQLite paths or PostgreSQL `PG*` settings used for backups. For
nested apps, move the initial files and set `prisma_config`, `prisma_schema_path` and
`prisma_migrations_path`.

- `prisma:validate` checks the schema offline and is included in `check`; `prisma:generate` builds
  the client.
- `prisma:makemigrations NAME` uses `--create-only`. Review the SQL. Prisma may require a shadow
  database or interactive drift resolution. `prisma:migrate` deploys committed migrations.
- `prisma:status` checks migration status; `prisma:format` formats the schema. Tasks preserve
  diagnostics and never automatically accept data loss or reset the database.

## Command reference

| Command | Purpose |
| --- | --- |
| `kitflow` | Prepare the local box |
| `kitflow box update` | Refresh the standard box |
| `kitflow init` | Choose or change project components |
| `kitflow update` | Apply updates, review individual edits or change setup |
| `kitflow status` / `kitflow diff` | List pending changes / show proposed differences |
| `kitflow config` | Show configuration paths without creating the box |
| `kitflow check` | Validate the box and connected project |
| `kitflow -i` / `-h` / `-v` | Read the offline guide / show help / show the version |

- `--project/-p PATH` targets another project. `--box/-b PATH` selects a box containing
  `kitflow-box.toml` for one command. Pass it each time you want that box.
- `init --components/-c IDS` supplies the complete comma-separated selection. Dependencies are added
  and omitted components are removed. Example: `kitflow init -c python,ruff,ty -y`.
- `--yes/-y` confirms safe changes. `update -y` skips the menu and keeps the saved selection.
  Conflicts stop unattended updates.
- `init --manage/-m ID` restores management of an excluded artifact with conflict review. Repeat it
  for multiple IDs. Use file rule IDs, `task.NAME` or `env.NAME`.

`kitflow check -b /path/to/box -p /path/to/project` validates definitions, dependencies, paths,
templates, wizard steps, TOML/JSON syntax and mise ownership blocks. It reports paths and reasons,
returns 0 for valid configurations or 2 for errors, and performs no writes, downloads or task runs.
It cannot validate tool-specific behavior. `status` and `diff` return 0 when current, 1 when changes
are pending and 2 on error.

To upgrade KitFlow, run `brew update` and `brew upgrade joynik/tap/kitflow`. This updates the
program. Your user-box `INSTRUCTION.md` takes priority when you run `kitflow -i`.
