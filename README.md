# KitFlow

KitFlow is a Python CLI for starting projects and maintaining configuration standards. Select
components in a keyboard- and mouse-driven interface, review the plan, and apply templates. The
first use downloads an example box; later operations use your local files without GitHub
synchronization.

## Install with Homebrew

Available after the first release is published.

```bash
brew install joynik/tap/kitflow
```

## Install from source

Requires Python 3.14 and uv:

```bash
uv tool install .
```

## Example

```bash
kitflow init
kitflow update
```

From this checkout, test unpublished templates with
`uv run kitflow init --project /path/to/project --catalog ./box`. See
[the user instructions](docs/INSTRUCTION.md) and [the box format](docs/CATALOG.md).

## Develop and build

```bash
uv sync
uv run pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
ty check src tests scripts
uv build
uv run --group build python scripts/build_standalone.py
```

`uv build` creates Python package distributions. The build script uses Nuitka standalone and creates
a platform-specific directory and installation archive in `dist/`. It requires a C compiler; Linux
standalone builds also require `patchelf`. Build separately on each target operating system and
architecture. The standalone application includes its runtime and dependencies, but no box
templates. GitHub Actions checks changes and builds release archives; see the
[workflow instructions](docs/INSTRUCTION.md#github-actions). Published releases update the Homebrew
formula automatically.
