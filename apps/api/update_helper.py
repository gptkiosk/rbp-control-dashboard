"""Host update helper: the only process that stages, switches or recovers an install.

Run from a pinned copy in <update root>/helper/ (with release_verify.py, update_engine.py and
helper.json beside it), never from a version directory it may replace, and always with
`python -I`. The API starts it detached for an operator's request; the supervisor unit runs
`recover` at login/boot and on a timer, so an update interrupted at any point is finished or
undone without the API.

    python -I update_helper.py status
    python -I update_helper.py drain
    python -I update_helper.py check [--channel stable|prerelease]
    python -I update_helper.py fetch <version> [--channel stable|prerelease] [--manifest-sha256 <hex>]
    python -I update_helper.py stage <inbox base name> [--manifest-sha256 <hex>]
    python -I update_helper.py apply <version id>
    python -I update_helper.py activate-initial <version id>
    python -I update_helper.py recover
    python -I update_helper.py restore-snapshot <snapshot id> --confirm-data-loss <snapshot id>

Prints one JSON object. Exit 0 on success, 1 when refused or failed, 2 on bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I does not add the script directory; use only the pinned copies

import release_fetch as rf  # noqa: E402
import update_engine as ue  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="update_helper.py")
    parser.add_argument("--config", default=str(HERE / "helper.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("drain")
    p = sub.add_parser("check")
    p.add_argument("--channel", choices=rf.CHANNELS, default="stable")
    p = sub.add_parser("fetch")
    p.add_argument("version")
    p.add_argument("--channel", choices=rf.CHANNELS, default="stable")
    p.add_argument("--manifest-sha256")
    p = sub.add_parser("stage")
    p.add_argument("name")
    p.add_argument("--manifest-sha256")
    sub.add_parser("apply").add_argument("version_id")
    sub.add_parser("activate-initial").add_argument("version_id")
    sub.add_parser("recover")
    p = sub.add_parser("restore-snapshot")
    p.add_argument("snapshot_id")
    p.add_argument("--confirm-data-loss", metavar="SNAPSHOT_ID", help="repeat the snapshot id to accept the data loss")
    args = parser.parse_args(argv)

    os.umask(0o077)
    try:
        ue.check_private_dir(HERE)
        cfg = ue.load_config(args.config)
        if args.command == "status":
            result = ue.status(cfg)
        elif args.command == "drain":
            blockers = ue.drain_blockers(cfg.db_path)
            result = {"drained": not blockers, "blockers": blockers}
        elif args.command == "check":
            found = rf.check(cfg, args.channel)
            result = {"available": found is not None, "candidate": rf.describe(found) if found else None}
        elif args.command == "fetch":
            result = rf.fetch_and_stage(cfg, args.channel, args.version, args.manifest_sha256)
        elif args.command == "stage":
            result = ue.stage(cfg, args.name, args.manifest_sha256)
        elif args.command == "apply":
            result = ue.apply(cfg, args.version_id)
        elif args.command == "activate-initial":
            result = ue.activate_initial(cfg, args.version_id)
        elif args.command == "restore-snapshot":
            result = ue.restore_snapshot(cfg, args.snapshot_id, args.confirm_data_loss)
        else:
            result = {"outcome": ue.recover(cfg)}
    except ue.UpdateError as exc:
        print(json.dumps({"ok": False, "problems": exc.problems}))
        return 1
    except rf.FetchError as exc:
        print(json.dumps({"ok": False, "problems": exc.problems}))
        return 1
    except OSError as exc:
        print(json.dumps({"ok": False, "problems": [f"{type(exc).__name__}: {exc.strerror or exc}"]}))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
