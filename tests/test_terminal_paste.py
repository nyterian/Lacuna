"""Real PTY regression: OS line discipline used to truncate long JSON lines."""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY regression")
@pytest.mark.parametrize("pretty", [False, True])
def test_real_terminal_pastes_long_unicode_json_without_truncation(tmp_path, pretty):
    import termios
    from lacuna.specification import example_request

    request = example_request()
    # One description line is >8 KB, far beyond macOS canonical MAX_CANON.
    request["profile"]["description"] = ("Long research scope with Unicode \u2014 evidence and methods. " * 170).strip()
    text = json.dumps(request, ensure_ascii=False, indent=2 if pretty else None)
    output = tmp_path / "request.json"
    master, slave = os.openpty()
    process = subprocess.Popen([sys.executable, "-m", "lacuna", "paste", "--out", str(output)],
                               cwd=Path(__file__).parents[1], stdin=slave, stdout=slave, stderr=slave,
                               env={**os.environ, "TERM": "xterm-256color", "PROMPT_TOOLKIT_NO_CPR": "1"})
    os.set_blocking(master, False)
    deadline = time.monotonic() + 20
    received = b""
    try:
        while b"json>" not in received and time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], .1)
            if readable:
                received += os.read(master, 65536)
        assert b"json>" in received, received[-2000:]
        assert not (termios.tcgetattr(slave)[3] & termios.ICANON), "Long input must bypass canonical line buffering"
        packet = b"\x1b[200~" + text.encode() + b"\x1b[201~\r"
        offset = 0
        while time.monotonic() < deadline:
            readable, writable, _ = select.select([master], [master] if offset < len(packet) else [], [], .05)
            if writable:
                offset += os.write(master, packet[offset:offset+2048])
            if readable:
                try:
                    received += os.read(master, 65536)
                except OSError:
                    break
            if process.poll() is not None:
                break
        assert process.wait(timeout=3) == 0, received[-3000:]
        assert offset == len(packet)
        saved = json.loads(output.read_text())
        assert saved["profile"]["description"] == request["profile"]["description"]
        assert saved["profile"]["concept_groups"] == request["profile"]["concept_groups"]
        # Terminal must be restored after the paste editor exits.
        assert termios.tcgetattr(slave)[3] & termios.ICANON
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)
