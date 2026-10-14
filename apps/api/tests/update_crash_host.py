"""Short-lived synthetic process for update crash tests: runs one engine operation and dies
with os._exit at a chosen point, so recovery sees exactly what a killed helper leaves behind.

    python -I update_crash_host.py '<json>'

json: {"config": {...HelperConfig fields...}, "platform": "...", "op": "stage"|"apply",
       "name"/"digest" (stage) or "version_id" (apply), "crash": "builder"|"stop"|"readiness",
       "calls": "<file that records service calls>"}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import release_verify as rv  # noqa: E402
import update_engine as ue  # noqa: E402


class RecordingService(ue.ServiceControl):
    def __init__(self, calls: str, crash_on_stop: bool):
        self.calls, self.crash_on_stop = calls, crash_on_stop

    def _record(self, verb: str) -> None:
        with open(self.calls, "a") as out:
            out.write(verb + "\n")

    def stop(self) -> None:
        self._record("stop")
        if self.crash_on_stop:
            os._exit(9)

    def start(self) -> None:
        self._record("start")


def main() -> None:
    args = json.loads(sys.argv[1])
    rv.host_platform = lambda: args["platform"]
    raw = args["config"]
    cfg = ue.HelperConfig(**{**raw, "root": Path(raw["root"]), "db_path": Path(raw["db_path"])})
    if args["op"] == "stage":
        def builder(cfg, app_dir, release):
            (app_dir / ue.RUNTIME_DIR).mkdir()
            os._exit(9)
        ue.stage(cfg, args["name"], args["digest"], builder=builder)
    else:
        def readiness(cfg, version, started):
            os._exit(9)
        ue.apply(cfg, args["version_id"], RecordingService(args["calls"], args["crash"] == "stop"),
                 readiness=readiness, blockers=lambda path: [])
    os._exit(0)  # not reached when the crash point is hit


if __name__ == "__main__":
    main()
