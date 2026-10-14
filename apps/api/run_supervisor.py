"""Detached supervisor for one agent run: python -I run_supervisor.py <exit-path> -- <argv...>

The dispatcher starts it as a new session (it leads the run's process group) with stdout
and stderr already pointing at the run's output files. It runs the agent with those
streams, then fsyncs the output and atomically writes {"returncode": n} (or
{"spawn_error": "..."}) to <exit-path>. Because nothing here depends on the API process,
the agent keeps running if the API dies; a restarted API reattaches by tailing the files
and waiting for the exit record. Its command line contains <exit-path>, which identifies
it for liveness checks. Standard library only.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys


def _record(exit_path: str, status: dict) -> None:
    for fd in (1, 2):
        try:
            os.fsync(fd)
        except OSError:
            pass
    temp = exit_path + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(status, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, exit_path)
    directory = os.open(os.path.dirname(exit_path) or ".", os.O_RDONLY)
    try:
        os.fsync(directory)
    except OSError:
        pass
    finally:
        os.close(directory)


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[2] != "--":
        print("usage: run_supervisor.py <exit-path> -- <argv...>", file=sys.stderr)
        return 2
    exit_path, command = argv[1], argv[3:]
    # Group signals reach the agent too. Keep waiting so its status is recorded; a
    # handler (unlike SIG_IGN) is reset to the default in the agent at exec.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: None)
    try:
        child = subprocess.Popen(command)
    except OSError as exc:
        _record(exit_path, {"spawn_error": str(exc)})
        return 127
    while True:
        try:
            code = child.wait()
            break
        except InterruptedError:  # pragma: no cover - PEP 475 retries wait()
            continue
    _record(exit_path, {"returncode": code})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
