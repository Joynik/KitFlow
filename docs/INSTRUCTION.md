# KitFlow instructions

KitFlow copies configuration from your local `box` and keeps project files up to date. A box
contains component definitions, file templates and mise task fragments.

```text
First use: GitHub example → ~/.config/kitflow
Everyday use: Local box → Component selection → Change plan → Confirmation → Project files
```

## Install and start

A standalone distribution includes the application runtime and dependencies. Keep its executable and
accompanying libraries together. The archive is extracted once during installation, not when the
command starts. Templates are not included in the executable or the standalone directory.

For installation from source, use Python 3.14 and uv:

```bash
uv tool install .
```

1. Open your project directory.
2. Run `kitflow init`.
3. Select components.
4. Review the plan and confirm it.

On first use, KitFlow downloads the example `box/` from its GitHub repository. It installs the
example in `~/.config/kitflow`. If `XDG_CONFIG_HOME` is set, KitFlow uses `$XDG_CONFIG_HOME/kitflow`
instead. An incomplete download is discarded before the user box becomes available. Run
`kitflow config` to display the local configuration location without downloading anything.

After that initial download, your box is independent of GitHub. KitFlow does not synchronize,
refresh or replace it automatically. An existing but invalid box produces an error instead of
triggering a replacement download.

## Your local box

```text
~/.config/kitflow/
├── kitflow-box.toml
├── templates/
└── tasks/
```

Edit these files directly to define your standards. Add components, change templates and adjust task
fragments as needed. You do not need a GitHub repository to maintain your box. Back up the `kitflow`
directory using your preferred backup tool. Restore it in the same configuration location on another
device. Local template edits become available to all projects that use this box.

Changes to the installed program do not replace your box. Use your own backup or file-management
workflow to replace the example or restore your standards. All referenced template files must exist.
Use `empty = true` with `mode = "once"` to create an empty document without a template.

## Initialize or configure a project

`kitflow init` opens the component selector. Running it again loads the existing selection so you
can add or remove components. Running `kitflow` without a subcommand also opens this selector.

Arrow keys move the highlight. Enter or Space toggles a selection. Tab changes the focused area. The
mouse selects entries and activates buttons. Ctrl+S opens the change plan. Escape cancels selection.

Mandatory dependencies are added automatically. The menu removes dependent components when you
deselect their prerequisite. KitFlow saves the resolved selection and installed file state in
`kitflow.toml`.

For non-interactive initialization or reconfiguration, supply the complete selection:

```bash
kitflow init --components python,ruff,ty,rumdl,agents --yes
kitflow init --components python,ruff,agents --yes
```

## Update a project

1. Edit your local box or the project's component selection as needed.
2. Run `kitflow update` in the project directory.
3. Review file additions, updates and removals.
4. Resolve any conflicts and confirm the plan.

`update` reads the current project selection and your current local templates. It does not contact
GitHub after the user box exists. You can also edit the component list directly in `kitflow.toml`
before updating. Keep the installed state tables: they detect local edits and identify obsolete
managed files.

Use `kitflow update --yes` to confirm a conflict-free plan automatically. `--yes` does not authorize
overwriting conflicting files.

## Ownership and conflicts

Ordinary managed configuration files are updated as whole files. Files are compared with the
checksums saved after the last installation. For a conflict, choose `replace`, `skip`, `keep` or
`quit`. `keep` makes the artifact user-owned and records an exclusion. During initial adoption,
skipping an existing user file also records an exclusion. An identical existing file is adopted
without replacement.

Unchanged files belonging to removed components are deleted after confirmation. Modified files
require a conflict decision. KitFlow does not recursively delete directories. Files with
`mode = "once"` are created only if absent and are never updated or deleted afterward.

Return an excluded artifact to management in the selector or run:

```bash
kitflow init --manage ARTIFACT-ID
```

Files are checked again after confirmation. A changed file cancels application. Writes use temporary
files and replacement; handled write failures trigger rollback. A directory lock prevents concurrent
KitFlow applications on macOS and Linux. This is not a durable multi-file transaction against power
loss or process termination.

## mise

KitFlow builds tasks and `[env]` entries from selected components. It does not install tools or
manage `[tools]`. Install the required tools separately, then run tasks with `mise run TASK`.

Matching task fragments are combined in catalog order with `set -eu` before the commands. Removing a
component rebuilds the managed tasks without its fragments.

Remove both KitFlow markers to take ownership of a task or environment entry. Removing only one
marker causes an error before files are written. Manual changes inside a marked block receive the
same conflict protection as whole files.

## Inspection and local testing

| Command | Purpose |
| --- | --- |
| `kitflow init` | Create or edit the project's component selection |
| `kitflow update` | Apply local templates to the current selection |
| `kitflow status` | Show pending changes without applying them |
| `kitflow diff` | Show file differences without applying them |
| `kitflow config` | Show the configuration directory and local box path |

`status` and `diff` return 0 when files are current and 1 when changes are pending. Commands return
2 for errors or unresolved non-interactive conflicts. Use `--project PATH` to operate on another
directory.

For an unpublished local example, bypass the user box for one operation:

```bash
kitflow init --catalog /path/to/box
kitflow update --catalog /path/to/box
```

This override does not install or replace the shared user box. Without `--catalog`, every project
uses the shared box in the configuration directory. Legacy remote-source metadata in a project does
not select a remote source. The next successful application records the local box model.

See [the box format reference](CATALOG.md) to define components and templates.

## GitHub Actions

`Checks` runs on branch pushes, pull requests and manual requests. It checks Ruff linting and
formatting, ty types and Python package builds. Tests run on Linux and macOS with Python 3.14.
Development tool versions come from `uv.lock`.

```text
Branch / PR → Checks
Version tag → Checks → Native builds → Checksums → Draft release
Manual release workflow → Checks → Native build artifacts
```

`Release` builds macOS ARM64, Linux ARM64 and Linux x86_64 archives. Each build extracts its archive
into a temporary directory and checks initialization and status using the example box. The archives
contain the runtime but no templates. Linux builds use Ubuntu 24.04; compatibility with older Linux
systems is not guaranteed. macOS deployment requirements depend on the build runner and bundled
Python runtime.

1. Prepare the version in `pyproject.toml` and a dated release section in `CHANGELOG.md`.
2. Commit the release changes after checks pass.
3. Create a matching `MAJOR.MINOR.PATCH` tag without a `v` prefix.
4. Push the tag when release preparation is authorized.
5. Review the generated draft, archives and `SHA256SUMS`.
6. Publish the draft when publication is authorized.

A manual run builds downloadable workflow artifacts without creating a release. Tag runs create a
draft only after all checks and builds pass. Existing releases are not overwritten; rerunning the
final creation step for the same release fails. Artifacts are retained for 14 days.

Private repositories use the workflow's built-in `GITHUB_TOKEN`. No personal token is required for
creating releases in the same repository. GitHub-hosted runner usage remains subject to the
account's Actions limits and billing. After publication, `Update Homebrew tap` updates
`Formula/kitflow.rb` in `Joynik/homebrew-tap`. It validates the published asset metadata against
`SHA256SUMS` before committing the formula. The `HOMEBREW_TAP_SSH_KEY` secret contains a
write-enabled deploy key restricted to the tap. A manual run with a published version can retry a
failed formula update without rebuilding. The updater refuses to downgrade an existing formula.

## Install and update with Homebrew

```bash
brew install joynik/tap/kitflow
brew update
brew upgrade joynik/tap/kitflow
```

The formula installs the standalone runtime without Python dependencies. Supported distribution
targets are macOS 15 or newer on ARM64, and Linux on ARM64 and x86_64. It does not replace your
local box.
