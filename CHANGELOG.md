# Changelog

## Unreleased

### Fixed

- Exclude Node dependencies, Bun lockfiles and rumdl files from VS Code extension packages.

## 0.13.3 — 2026-11-18

### Fixed

- Keep new mise settings outside managed task blocks when changing project setup.

- Compose `.vscodeignore` from the selected components, including agent instructions and tests.

## 0.13.2 — 2026-11-18

### Fixed

- Generate `.vscodeignore` for VS Code extensions. Preserve personal rules in marked `.vscodeignore`
  and `.dockerignore` files during updates.
- Show checks before build tools so Bun-based VS Code extension builds appear on the first pass.

## 0.13.1 — 2026-11-18

### Fixed

- Use green focus borders, row highlights and selection markers throughout the setup and update
  menus.

## 0.13.0 — 2026-11-18

### Added

- Review file changes side by side from the update menu and select individual text changes, mise
  tasks or settings.

### Changed

- Match terminal buttons and scrollbars to the green palette.

### Removed

- Use the update menu to review changes. The `update --reset` shortcut has been removed.

## 0.12.0 — 2026-11-18

### Added

- Set up a desktop VS Code extension from the Frameworks and Platform step. Choose Bun or esbuild
  for bundling, with optional extension tests and local VSIX packaging. Upgrade KitFlow to 0.12.0
  before refreshing the standard box to use these templates.

## 0.11.0 — 2026-11-17

### Added

- Select files to restore from box defaults with `update --reset`, optional diff previews and all
  checkboxes initially unchecked. Reset initial mise settings while keeping other user entries.

### Fixed

- Download the standard box as one archive instead of requesting each file separately.
- Normalize generated Python root and source paths and explain path variables with short comments.

## 0.10.0 — 2026-11-17

### Added

- Manage `.gitignore` with separate KitFlow and user blocks. Automatically replace only the KitFlow
  region without conflicts or diffs; preserve existing files with missing or damaged markers.
- Select Python package or Nuitka standalone builds, or leave Python builds disabled.
- Configure Python project and test directories independently from source checks.

### Changed

- Seed quiet mise task output for new settings without suppressing program diagnostics.
- Name Python paths `project_root`, `python_source` and `python_tests`, with matching environment
  overrides. Resolve relative source and test paths from the Python project root. Existing mise
  vars/env remain user-owned and must be renamed manually.

### Fixed

- Create `pyproject.toml` once and preserve it during updates and component removal, including
  projects that previously managed the file.
- Run pytest and unittest from the Python project directory instead of the source directory.

## 0.9.1 — 2026-11-17

### Added

- Add selectable Prisma ORM 7 with creation-only config and schema examples, explicit client and
  migration tasks, and schema validation in `check`.
- Add framework-specific, server, Rust and Prisma environment examples.
- Generate baseline mypy, pytest, rustfmt, SwiftLint and Swift formatter configurations for selected
  components.
- Add editable agent ignore fragments and conditional database, SQLite and test exclusions for
  Docker builds.

### Changed

- Rename database execution and SQLite parameters without legacy aliases. Resolve SQLite database
  paths from `.env` relative to the project root or accept absolute paths. Separate SQLite initial
  settings from shared database operations. Existing projects must manually rename `DATABASE_TARGET`
  to `DATABASE_EXECUTION_MODE`, `DATABASE_SQLITE_PATH` to `SQLITE_DATABASE_PATH`,
  `DATABASE_INIT_SQL` to `SQLITE_INIT_SQL`, and `DATABASE_DOCKER_SQLITE_PATH` to
  `SQLITE_CONTAINER_PATH`, plus their corresponding mise vars.

### Fixed

- Initialize user boxes with the current catalog schema. Warn during project and standard box
  updates when a user catalog needs a manual schema update, without rewriting the catalog.

## 0.9.0 — 2026-11-17

### Added

- Assemble managed text files from ordered, conditional UTF-8 fragments, with optional dotenv
  duplicate-variable checks.
- Add Docker-only `.dockerignore` and selectable mypy type checks with concise diagnostics.

### Changed

- Build `.gitignore` and `.env.example` from the selected components using standard box schema 4.
  `.env.example` now receives managed updates with conflict protection; `.env` remains user-owned.

## 0.8.1 — 2026-11-16

### Changed

- Choose update actions, conflict handling and plan confirmation from keyboard and mouse menus.
- Make selected components brighter in the setup wizard.

### Fixed

- Report when no project files need updating without an empty plan or confirmation.

## 0.8.0 — 2026-11-16

### Added

- Configure projects with a conditional Navigator wizard. Separate languages, frameworks, servers,
  databases, infrastructure and tools; preselect optional recommendations while preserving existing
  project choices. Define steps and visibility in the box.
- Add Flask, Next.js, Vue, Nuxt, Svelte, SvelteKit, Astro, Axum and Actix Web to the standard box,
  with framework dependencies, frontend script tasks and Rust backend run tasks.

### Changed

- Interactive `update` offers file updates or reconfiguration through the wizard. `update -y`
  continues to apply the saved selection without opening a menu.
- Use standard box schema 3 for wizard definitions. Legacy schema 1 and 2 catalogs remain readable.

### Removed

- Remove setup profiles and `--profile/-r`. Existing projects retain their resolved components; old
  local profile files are left untouched and ignored.

## 0.7.1 — 2026-11-16

### Fixed

- Exclude Finder `.DS_Store` metadata from standard box downloads, directory templates and box
  comparisons.

### Changed

- Apply `kitflow box update` without displaying differences or requesting confirmation.

## 0.7.0 — 2026-11-16

### Added

- Generate user-owned mise settings once, with configurable project directories, server defaults and
  `.env` overrides. Add task descriptions, arguments, aliases and alternative component conditions.
- Add default task help, selectable Granian/Gunicorn/Uvicorn dev and run modes, independent test
  runners, SwiftPM/Xcode, Alembic, translations and composed debug/release builds.
- Add SQL backups and restores for SQLite and PostgreSQL, locally or through Compose, with overwrite
  protection, SQLite staging and PostgreSQL transaction rollback.
- Compose `mise check` from selected lint, format and type checks, including Django migration
  checks.
- Add lint fixes, Markdown and Django HTML formatting checks, Django tests, Rust documentation tests
  and Vite preview tasks to the standard box.

### Changed

- Use concise diagnostics for standard quality tasks while preserving warnings and failures.
- Run Django management commands through `uv run python manage.py`.
- Upgrade the standard box to schema 2. Upgrade KitFlow before refreshing the standard box; schema 1
  user boxes remain supported.

### Fixed

- Show an immediate download notice during initial box setup and `kitflow box update`.

## 0.6.0 — 2026-11-15

### Added

- Standard box updates through `kitflow box update`, with a separate `default/` layer, user
  overrides, stable fragment IDs and explicit disabled entries. Existing flat boxes remain usable.
- Add a Tauri + React desktop profile with Rust, JavaScript, TypeScript, Vite, SQLite and Bun.
- Compose Rust and native Bun linting, type checks, formatting and tests, with Tauri development and
  build tasks. Rust tasks support root workspaces and the standard `src-tauri` layout.

## 0.5.0 — 2026-11-13

### Added

- Choose one local profile from `profiles/*.toml` during `init`, with actions to review the plan or
  customize the selection. Use `--profile/-r` for setup without the menu.
- Validate profile fields, dependencies and conflicts with `kitflow check`. Projects save the final
  selection, so profile edits do not change existing projects during `update`.
- Include Python, Django and Django + Docker example profiles in standard box setup and refresh.

## 0.4.0 — 2026-11-13

### Added

- Preserve relative symbolic links as links without traversing or validating target contents, with
  conflict protection and safe removal. Absolute links are rejected.
- Use directory templates, including hidden files and nested directories, with per-file updates,
  conflict protection and TOML/JSON validation. Personal files are preserved.

### Fixed

- Show `--help, -h` in the same long-option-first order as other CLI options.

## 0.3.0 — 2026-11-13

### Added

- Validate the box and connected project with `kitflow check`, including schema fields,
  dependencies, template availability, TOML/JSON syntax and managed mise blocks. Checks work offline
  without writes.

### Changed

- Navigate the component selector with arrow keys: Right enters components, Left returns to
  categories, and Tab focuses the action buttons. The selector starts with categories focused.

## 0.2.0 — 2026-11-13

### Fixed

- Prevent the standalone component selector from crashing while inspecting Textual event
  annotations.

### Added

- Support `-v` as a short alias for `--version`.
- Describe commands in help and add `-p`, `-b`, `-c` and `-m` shortcuts.
- Read the concise English usage guide offline with `--instruction` or `-i`.
- Include `INSTRUCTION.md` when preparing a new user box.
- Offer to refresh the standard box on repeated startup, with per-file differences and confirmation
  while preserving personal files.

### Changed

- Running `kitflow` without a command prepares the box without configuring a project. Use `init` to
  create or change project selections.
- Use `--box` instead of `--catalog` to select a box for one command. The old option remains
  accepted for compatibility.

## 0.1.0 — 2026-11-10

### Changed

- Store the local box directly in `~/.config/kitflow`, without a nested `box/` directory.
- The box manifest is named `kitflow-box.toml`.
- The first use installs the example `box/` in the user configuration directory once.
- Project operations use user-owned local templates without GitHub synchronization or a remote
  cache.
- Repeating `init` edits the existing selection; `update` applies it. The separate `change` command
  was removed.
- The example uses generic instructions and excludes tool-specific skills and graph tasks.

### Added

- Automatic Homebrew formula updates after release publication.
- GitHub checks and native build workflows for macOS ARM64 and Linux ARM64/x86_64, with checksums
  and draft releases.
- Empty document creation without template files using `empty = true` and `mode = "once"`.
- English CLI, interface, example Box and user documentation.
- Interactive component selection with keyboard and mouse support.
- Declarative templates and composed mise tasks from a local box.
- Project initialization, reconfiguration, update plans, status and file differences.
- Local edit protection, persistent ownership exclusions and guarded component removal.
- A local catalog override for development without user-box initialization.
