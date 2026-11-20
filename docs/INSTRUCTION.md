# Using KitFlow

KitFlow generates project configuration and composes tasks for mise. Install the tools separately.

```text
Prepare the box → Choose project components → Configure mise → Run tasks → Review updates
```

## Box setup

Run `kitflow` once. It downloads the standard Box to `~/.config/kitflow/standard/` and creates
`personal/` alongside it. With `XDG_CONFIG_HOME` set, the root is `$XDG_CONFIG_HOME/kitflow`.

Copy `standard/templates/ruff.toml` to `personal/templates/ruff.toml` to customize Ruff. Use
`personal/kitflow-box.toml` to add, replace or disable rules. See the
[catalog reference](https://github.com/Joynik/KitFlow/blob/main/docs/CATALOG.md).

You can point `personal/` at a directory in your Obsidian vault with a symbolic link. Move your
personal Box into the vault first, then create the link at its former location. KitFlow can also
read a linked `standard/` directory. Keep `standard/` as an ordinary directory for
`kitflow upgrade`.

`kitflow upgrade` replaces only the downloaded standard Box. Both `update` and `upgrade` stop and
identify any inaccessible Box link.

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

The standard Box has a numbered revision. `kitflow upgrade` installs the latest stamped revision.
Each project records its applied revision in `kitflow.toml`. If a migration is needed,
`kitflow update` prompts for it before showing the update menu. Legacy projects without a revision
start at Box 0. The temporary transition to Box 1 tracks known Translation keys when Translation is
enabled, or offers to remove them when it is disabled. It preserves other keys.

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
  absent. Ordinary updates preserve them. Language manifests also accept missing dependency and
  configuration entries for selected tools. KitFlow keeps existing values and leaves these entries
  in place if you later deselect the tool.
- **Ignore files** (`.gitignore`, `.dockerignore`, `.vscodeignore`) update only inside `# <kitflow>`
  / `# </kitflow>`. Put personal rules inside `# <user>` / `# </user>`. Missing or damaged KitFlow
  markers leave the file untouched. To opt in an existing file, add an empty KitFlow block above
  your rules, then restore management with `init -m .gitignore` if excluded. If an existing
  extension manifest has a `files` list, remove it before packaging with `.vscodeignore`. Move any
  packaging rules you still need into the user block.
- **`mise.toml`** uses marked tasks and environment entries. Remove both markers to take ownership
  of an entry. Ordinary updates preserve vars, env and settings. Deselecting a component removes
  keys KitFlow added for it, even after edits, unless another selected component needs them. Keys
  without ownership records stay in place unless a confirmed migration covers them. If you skip
  removing a departing mise task, its settings stay until you remove the task.
- **Environment files** are optional. In **Environments**, select **Create .env.example** to
  generate an example from the selected mise defaults and application fragments. To configure the
  project through `.env`, run `mise run env:local` once and edit the copy. Leave **Create .env**
  unchecked for this workflow. Select it to start with an empty local file instead. KitFlow
  preserves an existing `.env`. Edit custom fragments in your box under `templates/gitignore/`,
  `templates/dockerignore/`, `templates/vscodeignore/` or `templates/env/`.

## Run and configure mise tasks

Run `mise run help` to list the tasks your project actually has. Shared tasks combine fragments from
the selected components.

| Task | Purpose |
| --- | --- |
| `check` | Run lint, format, type and configured migration or schema checks without fixes |
| `check-unused`, `check-deps` | Report potentially unused code or dependency issues for selected tools |
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

Install the project's development dependencies before running its optional code and dependency
checks. For a uv project, run `uv sync`; for a Bun project, run `bun install`. For Cargo Machete,
run `mise run install-cargo-machete` once to install its executable under the Rust project's
`target/` directory. These checks report findings without applying fixes.

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

- **Python servers.** The wizard offers Granian, Gunicorn, Uvicorn or Gunicorn + Uvicorn for Django,
  Granian or Uvicorn for FastAPI, and Granian or Gunicorn for Flask. Set `python_app` to
  `module:object` using the interface your server expects. In the combined Django mode, use the ASGI
  entry point. `dev` uses Uvicorn and `run` uses Gunicorn with the `uvicorn-worker` package.
- **Reload exclusions.** For Granian and Uvicorn-based development, set `server_reload_ignore_dirs`
  and `server_reload_ignore_patterns` in mise `[vars]`, one entry per line. Override them in `.env`
  with `SERVER_RELOAD_IGNORE_DIRS` and `SERVER_RELOAD_IGNORE_PATTERNS`. Granian needs
  `granian[reload]` and takes directory names and regular expressions. Uvicorn needs `watchfiles`
  (included in `uvicorn[standard]`) and takes existing directories relative to `python_source` or
  absolute paths, plus glob patterns. Gunicorn's built-in reload has no exclusions.
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

- **SQLite.** With `SQLITE_MODE="local"`, set `SQLITE_DATABASE_PATH` to an absolute path or a path
  relative to mise.toml. `db:prepare` creates a new file and accepts initial SQL via
  `SQLITE_INIT_SQL`. With `SQLITE_MODE="remote"`, configure your application driver to read
  `SQLITE_REMOTE_URL` and, when required, `SQLITE_REMOTE_AUTH_TOKEN`. Use the provider's tools for
  initialization, backup and restore. KitFlow's SQLite file tasks stop in remote mode.
- **PostgreSQL.** Set `PGHOST`, `PGPORT`, `PGDATABASE` and `PGUSER`. Keep passwords in `.pgpass` or
  local environment settings.
- **Docker.** Set `DOCKER_SOURCE="deployment"` to find `compose.yml` in that folder. A relative
  `COMPOSE_FILE` is resolved inside `DOCKER_SOURCE`. An absolute path selects a file directly.
  `COMPOSE_ENV_FILE` defaults to `.env` next to mise.toml. Set
  `COMPOSE_WRAPPER="deployment/compose.sh"` to pass Compose subcommands to your own shell script.
  Tasks include `docker:build`, `docker:check`, `docker:up`, `docker:status`, `docker:logs` and
  `docker:down`. Down preserves volumes. Use `docker:db:backup FILE`, `docker:db:restore FILE`, or
  `--docker` on the ordinary database task. `DATABASE_EXECUTION_MODE` selects `native` or `docker`.
  Set `database_docker_service` and, for SQLite, `SQLITE_CONTAINER_PATH`. The running container
  needs the database client and its connection settings. SQLite restore also needs a POSIX shell in
  the container.

### Test databases

After selecting a Python test runner, choose SQLite or PostgreSQL under **Test database**. Leave
both unselected to use the test runner's existing configuration. SQLite defaults to `:memory:`. Set
`TEST_SQLITE_DATABASE_PATH` for a separate file. For PostgreSQL, set `TEST_DATABASE_URL` in `.env`
with a dedicated database and a user restricted to that database. The test task checks these values
before invoking the runners. Configure your fixtures or test settings to read them. For Django, set
`DJANGO_TEST_SETTINGS_MODULE` to a dedicated module that reads `TEST_DATABASE_BACKEND` and the
corresponding test connection settings.

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
| `kitflow upgrade` | Refresh the standard box |
| `kitflow init` | Choose or change project components |
| `kitflow update` | Apply updates, review individual edits or change setup |
| `kitflow status` / `kitflow diff` | List pending changes / show proposed differences |
| `kitflow config` | Show configuration paths without creating the box |
| `kitflow check` | Validate the box and connected project |
| `kitflow show` | Print what the local Box generates for the selected components |
| `kitflow -i` / `-h` / `-v` | Read the offline guide / show help / show the version |

- `--project/-p PATH` targets another project. `--box/-b PATH` selects a box containing
  `kitflow-box.toml` for one command. Pass it each time you want that box.
- `init --components/-c IDS` supplies the complete comma-separated selection. Dependencies are added
  and omitted components are removed. Example: `kitflow init -c python,ruff,ty -y`.
- Use `show files`, `show tasks` and `show components` to discover names. Then run
  `kitflow show file pytest.ini`, `kitflow show file .env.example`, `kitflow show task docker:up` or
  `kitflow show defaults`. Pass the complete hypothetical selection with `--components` to preview
  an addition or removal. Show reads the local Box and the saved selection without reading project
  values from `.env` or changing files.
- `--yes/-y` confirms the plan, including pending migrations. `update -y` keeps the saved selection.
  Conflicts stop unattended updates.
- In **User-owned files and blocks**, the setup wizard groups files, mise tasks and environment
  variables. File names omit directories. KitFlow tracks the paths internally.
- `init --manage/-m ID` restores management with conflict review. Use the full file name without
  directories or the mise block ID, such as `task.lint`. Repeat it for multiple entries.

`kitflow check -b /path/to/box -p /path/to/project` validates definitions, dependencies, paths,
templates, wizard steps, TOML/JSON syntax and mise ownership blocks. It reports paths and reasons,
returns 0 for valid configurations or 2 for errors, and performs no writes, downloads or task runs.
It cannot validate tool-specific behavior. `status` and `diff` return 0 when current, 1 when changes
are pending and 2 on error.

To upgrade KitFlow, run `brew update` and `brew upgrade joynik/tap/kitflow`. This updates the
program. Your user-box `INSTRUCTION.md` takes priority when you run `kitflow -i`.
