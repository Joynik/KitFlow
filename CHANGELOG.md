# Changelog

## Unreleased

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
