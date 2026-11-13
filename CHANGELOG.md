# Changelog

## Unreleased

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
