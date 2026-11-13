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

KitFlow downloads the example box into `~/.config/kitflow`. It does not change your project. If you
use `XDG_CONFIG_HOME`, the location is `$XDG_CONFIG_HOME/kitflow` instead.

On later runs, KitFlow asks whether to download updates for the standard box. Answer **No** to keep
your box without contacting GitHub. Answer **Yes** to download a preview. KitFlow shows each
differing file and asks before applying it. Decline a file to keep your version. Personal files are
not deleted. KitFlow checks the combined configuration before writing. A failed download leaves your
box unchanged.

```text
~/.config/kitflow/
├── INSTRUCTION.md       This guide
├── kitflow-box.toml     Available components and rules for applying files
├── templates/           Configuration files and agent instructions
└── tasks/               Shell commands used to build mise tasks
```

Edit this directory yourself and keep a backup. For example, change `templates/ruff.toml` to define
your Ruff settings. The next project update will offer those settings. See `docs/CATALOG.md` in the
KitFlow repository for the box format.

## Set up a project

```bash
cd /path/to/project
kitflow init
```

1. Choose components, such as Python, Ruff and agent instructions.
2. Use arrows to move and Enter or Space to select. Tab changes the focused area; mouse clicks work
   too.
3. Press Ctrl+S or click **Review plan**.
4. Review the proposed changes and confirm. Escape cancels the menu.

Required dependencies are selected automatically. KitFlow saves the selection and managed file state
in the project's `kitflow.toml`. Keep this file, including its state tables. Run `kitflow init`
again to add or remove components.

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

| Command | Purpose |
| --- | --- |
| `kitflow` | Prepare the local box, or offer to review box updates |
| `kitflow init` | Choose or change project components |
| `kitflow update` | Apply the current box to the saved selection |
| `kitflow status` | List pending changes |
| `kitflow diff` | Show proposed file differences |
| `kitflow config` | Show configuration paths without creating the box |
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
