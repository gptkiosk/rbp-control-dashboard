"""Out-of-app recovery CLI: status, list versions, roll back, restore a data snapshot.

Run from the pinned copy in <update root>/helper/ (beside update_engine.py, release_verify.py and
helper.json), always with `python -I`. It never contacts the API and needs neither a sign-in nor a
running service: it reads the install journal and version links on disk and drives the same engine
as update_helper.py, so it works when the app is down or will not start.

    python -I update_recovery.py status
    python -I update_recovery.py versions
    python -I update_recovery.py snapshots
    python -I update_recovery.py rollback           [--confirm <previous version id>]
    python -I update_recovery.py restore <snapshot>  [--confirm <snapshot id>]
    python -I update_recovery.py recover            [--yes]

Anything that changes the install asks first and shows what it will do. A prompt is answered by
typing the version or snapshot id back; with no terminal, the same id must be given in --confirm,
otherwise nothing is changed. Add --json for one machine-readable object. Exit 0 done, 1 refused
or failed, 2 bad usage, 3 declined at the prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, TextIO

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I does not add the script directory; use only the pinned copies

import update_engine as ue  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DECLINED = 0, 1, 2, 3


class Declined(Exception):
    """The operator did not confirm, so nothing was changed."""


def stamp(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(value))


def probe_health(cfg: ue.HelperConfig) -> dict:
    """One short look at the public health endpoint. The app being down is a normal answer here."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(cfg.health_url, timeout=3) as resp:
            body = json.loads(resp.read(ue.MAX_HEALTH_BYTES + 1)[:ue.MAX_HEALTH_BYTES])
        if not isinstance(body, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        return {"reachable": False, "detail": f"no healthy answer ({type(exc).__name__})"}
    return {"reachable": True, "status": body.get("status"), "version": body.get("version"),
            "uptime_s": body.get("uptime_s")}


def rollback_plan(cfg: ue.HelperConfig) -> dict:
    """What a rollback would do, without changing anything. `problems` lists why it cannot run."""
    info = ue.status(cfg)
    current, previous = info["current"], info["previous"]
    problems: list[str] = []
    if info["tx"]:
        problems.append("an earlier update was interrupted; run recover first")
    if not current or not ue.read_receipt(cfg, current):
        problems.append("no managed current version; this install is updated by hand")
    if not previous:
        problems.append("there is no previous version to return to")
    elif not ue.read_receipt(cfg, previous):
        problems.append(f"previous version {previous} is missing or not completely staged")
    schema = None
    if previous and not problems:
        try:
            schema = ue.database_revision(cfg.db_path)
            if not ue.schema_compatible(schema, ue.known_revisions(cfg.versions / previous)):
                problems.append(f"the database is on schema {schema}, which {previous} does not know; restore a "
                                "snapshot taken on an older schema first (restore), then roll back")
        except ue.UpdateError as exc:
            problems.extend(exc.problems)
    return {"current": current, "previous": previous, "schema": schema, "problems": problems,
            "blockers": ue.drain_blockers(cfg.db_path)}


class Cli:
    def __init__(self, cfg: ue.HelperConfig, out: TextIO, ask: Callable[[str], str] | None, as_json: bool,
                 service: ue.ServiceControl | None = None, readiness: ue.Readiness = ue.health_readiness):
        self.cfg, self.out, self.ask, self.as_json = cfg, out, ask, as_json
        self.service, self.readiness = service, readiness
        self.result: dict = {}

    def say(self, text: str = "") -> None:
        if not self.as_json:
            print(text, file=self.out)

    def confirm(self, expected: str, given: str | None, what: str) -> None:
        """Type `expected` back at the prompt, or pass it as --confirm when there is no terminal."""
        if given is not None:
            if given != expected:
                raise Declined(f"--confirm did not match {expected}")
            return
        if self.ask is None:
            raise Declined(f"no terminal to ask on; to {what}, repeat the id with --confirm {expected}")
        try:
            answer = self.ask(f"Type {expected} to {what}, anything else cancels: ")
        except EOFError:
            answer = ""
        if answer.strip() != expected:
            raise Declined("cancelled")

    # --- read-only ---

    def status(self) -> dict:
        info = ue.status(self.cfg)
        health = probe_health(self.cfg)
        blockers = ue.drain_blockers(self.cfg.db_path)
        by_id = {v["id"]: v for v in info["versions"]}
        cur = by_id.get(info["current"]) or {}
        self.result = {"product": self.cfg.product, "root": str(self.cfg.root), "app": health,
                       "current": info["current"], "current_version": cur.get("version"),
                       "previous": info["previous"], "interrupted_update": info["tx"],
                       "last": info["last"], "snapshots": len(info["snapshots"]), "drain_blockers": blockers}
        self.say(f"Install root   {self.cfg.root}")
        self.say(f"App            " + (f"UP, reports version {health['version']} ({health['status']})"
                                       if health["reachable"] else f"DOWN - {health['detail']}"))
        self.say(f"Current        {info['current'] or 'none'}")
        self.say(f"Previous       {info['previous'] or 'none'}")
        if info["tx"]:
            tx = info["tx"]
            self.say(f"INTERRUPTED    {tx.get('kind')} {tx.get('id')} in phase {tx.get('phase')} "
                     f"(target {tx.get('target')}); run: recover")
        last = info["last"]
        if last:
            self.say(f"Last outcome   {last.get('outcome')} at {stamp(last.get('at'))}: {last.get('detail')}")
        self.say(f"Snapshots      {len(info['snapshots'])} kept")
        self.say("Work in flight " + ("none" if not blockers else "; ".join(blockers)))
        return self.result

    def versions(self) -> dict:
        info = ue.status(self.cfg)
        rows = []
        for v in info["versions"]:
            mark = "current" if v["id"] == info["current"] else "previous" if v["id"] == info["previous"] else ""
            rows.append({**v, "role": mark})
        self.result = {"versions": rows, "current": info["current"], "previous": info["previous"]}
        if not rows:
            self.say("No versions are installed.")
        for v in rows:
            state = "ok" if v["complete"] else "INCOMPLETE"
            self.say(f"{v['role']:<9} {v['id']}  {v['version'] or '?'}  {state}  staged {stamp(v['staged_at'])}")
        return self.result

    def snapshots(self) -> dict:
        snaps = ue.snapshots(self.cfg)
        self.result = {"snapshots": snaps}
        if not snaps:
            self.say("No data snapshots are kept.")
        for s in snaps:
            self.say(f"{s['tx']}  taken {stamp(s['created_at'])}  schema {s['schema_revision'] or 'none'}  "
                     f"{s['bytes']} bytes  before leaving {s['from_version'] or '?'}")
        return self.result

    # --- changes ---

    def _skip_drain(self, blockers: list[str], allow: bool) -> Callable[[Path], list[str]]:
        """Blockers normally stop a switch. With the app down, rows of runs that died with it are stale,
        so the operator may knowingly skip the check; never while the app is answering."""
        if not blockers:
            return ue.drain_blockers
        if not allow:
            return ue.drain_blockers
        if probe_health(self.cfg)["reachable"]:
            raise ue.UpdateError(["the app is answering, so its work is live; drain it instead of --skip-drain"])
        if self.ask is None:
            raise Declined("--skip-drain needs a terminal to confirm")
        self.say("The app is down but the database still lists work in flight (probably runs that died with it):")
        for line in blockers:
            self.say(f"  - {line}")
        self.confirm("skip-drain", None, "ignore these and continue")
        return lambda _path: []

    def rollback(self, confirm: str | None, skip_drain: bool) -> dict:
        plan = rollback_plan(self.cfg)
        self.result = {"plan": plan}
        self.say(f"Roll back: {plan['current']}  ->  {plan['previous']}")
        if plan["problems"]:
            raise ue.UpdateError(["rollback refused"] + plan["problems"])
        self.say("The service is stopped, a copy of the database is kept, the link is switched and the "
                 "service is started again. Data is not rolled back; use restore for that.")
        blockers_fn = self._skip_drain(plan["blockers"], skip_drain)
        if plan["blockers"] and blockers_fn is ue.drain_blockers:
            raise ue.UpdateError(["drain first; nothing was stopped"] + plan["blockers"])
        self.confirm(plan["previous"], confirm, f"roll back to {plan['previous']}")
        done = ue.apply(self.cfg, plan["previous"], self.service, self.readiness, blockers_fn)
        self.result = {"rolled_back": True, **done}
        self.say(f"Done. Current is now {done['current']}. {done['detail']}")
        return self.result

    def restore(self, snapshot_id: str, confirm: str | None, skip_drain: bool) -> dict:
        meta = ue.load_snapshot(self.cfg, snapshot_id)
        self.say(f"Restore snapshot {snapshot_id}: taken {stamp(meta['created_at'])}, schema "
                 f"{meta['schema_revision'] or 'none'}, before leaving {meta.get('from_version') or '?'}")
        self.say("WARNING: this discards every change made to the database since then. A copy of the "
                 "current database is kept first.")
        blockers = ue.drain_blockers(self.cfg.db_path)
        blockers_fn = self._skip_drain(blockers, skip_drain)
        if blockers and blockers_fn is ue.drain_blockers:
            raise ue.UpdateError(["drain first; nothing was stopped"] + blockers)
        self.confirm(snapshot_id, confirm, "discard newer data and restore")
        done = ue.restore_snapshot(self.cfg, snapshot_id, snapshot_id, self.service, self.readiness, blockers_fn)
        self.result = {"restored": True, **done}
        self.say(f"Done. {done['detail']}")
        return self.result

    def recover(self, yes: bool) -> dict:
        info = ue.status(self.cfg)
        tx = info["tx"]
        if not tx:
            self.result = {"outcome": "nothing to recover"}
            self.say("Nothing to recover.")
            return self.result
        self.say(f"Interrupted {tx.get('kind')} {tx.get('id')} in phase {tx.get('phase')}; recovery finishes it "
                 "or returns to the old version.")
        self.confirm("recover", "recover" if yes else None, "run recovery")
        outcome = ue.recover(self.cfg, self.service, self.readiness)
        self.result = {"outcome": outcome}
        self.say(f"Outcome: {outcome}")
        return self.result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="update_recovery.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", default=str(HERE / "helper.json"))
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "versions", "snapshots"):
        sub.add_parser(name)
    p = sub.add_parser("rollback")
    p.add_argument("--confirm", metavar="VERSION_ID", help="the previous version id, when there is no terminal")
    p.add_argument("--skip-drain", action="store_true", help="app down only: ignore stale work-in-flight rows")
    p = sub.add_parser("restore")
    p.add_argument("snapshot_id")
    p.add_argument("--confirm", metavar="SNAPSHOT_ID", help="the snapshot id, when there is no terminal")
    p.add_argument("--skip-drain", action="store_true", help="app down only: ignore stale work-in-flight rows")
    sub.add_parser("recover").add_argument("--yes", action="store_true", help="skip the question")
    return parser


def main(argv: list[str] | None = None, *, out: TextIO | None = None, ask: Callable[[str], str] | None = None,
         interactive: bool | None = None, service: ue.ServiceControl | None = None,
         readiness: ue.Readiness = ue.health_readiness) -> int:
    out = out or sys.stdout
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        ask = None
    elif ask is None:
        ask = input

    os.umask(0o077)
    try:
        ue.check_private_dir(HERE)
        cfg = ue.load_config(args.config)
        ue.prepare_layout(cfg)
        cli = Cli(cfg, out, ask, args.json, service, readiness)
        if args.command == "status":
            cli.status()
        elif args.command == "versions":
            cli.versions()
        elif args.command == "snapshots":
            cli.snapshots()
        elif args.command == "rollback":
            cli.rollback(args.confirm, args.skip_drain)
        elif args.command == "restore":
            cli.restore(args.snapshot_id, args.confirm, args.skip_drain)
        else:
            cli.recover(args.yes)
    except Declined as exc:
        print(json.dumps({"ok": False, "declined": str(exc)}) if args.json else f"Nothing was changed: {exc}",
              file=out)
        return EXIT_DECLINED
    except ue.UpdateError as exc:
        print(json.dumps({"ok": False, "problems": exc.problems}) if args.json
              else "Refused or failed:\n" + "\n".join(f"  - {p}" for p in exc.problems), file=out)
        return EXIT_FAILED
    except OSError as exc:
        print(json.dumps({"ok": False, "problems": [f"{type(exc).__name__}: {exc.strerror or exc}"]}) if args.json
              else f"Failed: {type(exc).__name__}: {exc.strerror or exc}", file=out)
        return EXIT_FAILED
    if args.json:
        print(json.dumps({"ok": True, **cli.result}, sort_keys=True, default=str), file=out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
