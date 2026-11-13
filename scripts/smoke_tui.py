"""Verify that a standalone executable opens and cancels its interactive selector."""

import os
import pty
import select
import subprocess
import sys
import tempfile
import time

with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as executable_dir:
    executable = os.path.join(executable_dir, "kitflow")
    os.symlink(os.path.abspath(sys.argv[1]), executable)
    environment = {**os.environ, "TERM": "xterm-256color", "XDG_CONFIG_HOME": project + "/config"}
    guide = subprocess.run([executable, "-i"], capture_output=True, check=True, env=environment)
    assert b"Using KitFlow" in guide.stdout, guide.stdout
    assert not os.listdir(project), "Reading instructions must not create a user box"
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [executable, "init", "--box", os.path.abspath("box"), "--project", project],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
    )
    os.close(slave)
    output = bytearray()
    started = time.monotonic()
    sent = False
    try:
        while time.monotonic() - started < 15:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
            if not sent and time.monotonic() - started > 2:
                os.write(master, b"\x1b")
                sent = True
            if process.poll() is not None:
                break
        process.wait(timeout=3)
        assert process.returncode == 0, process.returncode
        assert b"Traceback" not in output, output[-5000:]
        assert b"Choose components." in output, output[-1000:]
        assert b"Cancelled. No files were changed." in output, output[-1000:]
        assert not os.listdir(project), os.listdir(project)
        print("Standalone instructions, interactive startup and Escape cancellation passed.")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
