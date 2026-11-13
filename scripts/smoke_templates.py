"""Verify directory and relative-link management with the installed executable."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

executable = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix="kitflow-templates-") as temporary:
    root = Path(temporary)
    box, project = root / "box", root / "project"
    templates = box / "templates"
    (templates / ".nested").mkdir(parents=True)
    (templates / ".nested/example.pdf").write_bytes(b"%PDF-1.7\n\x00\xff")
    (templates / ".skill").symlink_to("../skills/example")
    (box / "kitflow-box.toml").write_text("""schema = 1
[[components]]
id = "example"
label = "Example"
category = "Tools"
[[files]]
id = "settings"
path = ".settings"
template = "templates"
when = ["example"]
""")
    (box / "profiles").mkdir()
    profile = box / "profiles/example.toml"
    profile.write_text('name = "Example"\ncomponents = ["example"]\n')
    project.mkdir()

    def run(command: str, *arguments: str, expected: int = 0) -> str:
        result = subprocess.run(
            [executable, command, "-b", str(box), "-p", str(project), *arguments],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "XDG_CONFIG_HOME": str(root / "config")},
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return result.stdout

    run("init", "-r", "example", "-y")
    output = project / ".settings"
    assert (output / ".nested/example.pdf").read_bytes() == b"%PDF-1.7\n\x00\xff"
    assert os.readlink(output / ".skill") == "../skills/example"
    run("check")
    (output / "personal.txt").write_text("Keep me")
    profile.write_text('name = "Example"\ncomponents = []\n')
    (templates / ".skill").unlink()
    (templates / ".skill").symlink_to("../skills/updated")
    assert "symlink -> ../skills/updated" in run("diff", expected=1)
    run("update", "-y")
    assert os.readlink(output / ".skill") == "../skills/updated"
    run("check")
    run("init", "-c", "", "-y")
    assert not (output / ".skill").is_symlink()
    assert not (output / ".nested/example.pdf").exists()
    assert (output / "personal.txt").read_text() == "Keep me"
    assert not (root / "config").exists()
print("Directory, binary file and relative-link smoke checks passed.")
