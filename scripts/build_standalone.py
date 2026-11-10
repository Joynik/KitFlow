"""Build a standalone directory and an installation archive for the current platform."""

import argparse
import os
import platform
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4, help="Parallel C compilation jobs")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    system = {"Darwin": "macos", "Linux": "linux"}.get(platform.system())
    if system is None:
        parser.error("Standalone builds currently support macOS and Linux")
    root = Path(__file__).resolve().parents[1]
    architecture = platform.machine().lower()
    architecture = {"aarch64": "arm64", "amd64": "x86_64"}.get(architecture, architecture)
    supported = {"macos": {"arm64"}, "linux": {"arm64", "x86_64"}}
    if architecture not in supported[system]:
        parser.error(f"Unsupported standalone target: {system}-{architecture}")
    output = root / "dist/standalone" / f"{system}-{architecture}"
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=standalone",
        "--output-filename=kitflow",
        f"--output-dir={output}",
        f"--jobs={args.jobs}",
        "--include-package=kitflow",
        "--include-package=textual",
        "--include-package-data=textual",
        "--include-package-data=rich",
        "--include-package-data=certifi",
        f"--report={output / 'compilation-report.xml'}",
        str(root / "scripts/standalone_entry.py"),
    ]
    environment = os.environ.copy()
    environment.setdefault("NUITKA_CACHE_DIR", str(root / "dist/nuitka-cache"))
    subprocess.run(command, cwd=root, env=environment, check=True)
    distributions = list(output.glob("*.dist"))
    if len(distributions) != 1:
        raise RuntimeError("Expected one standalone distribution directory")
    distribution = distributions[0]
    subprocess.run([str(distribution / "kitflow"), "--version"], check=True)
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    archive = root / "dist" / f"kitflow-{version}-{system}-{architecture}.tar.gz"
    temporary = archive.with_suffix(".tmp")
    try:
        with tarfile.open(temporary, "w:gz") as bundle:
            bundle.add(distribution, arcname="kitflow")
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Standalone directory: {distribution}")
    print(f"Installation archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
