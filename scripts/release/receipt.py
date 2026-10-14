#!/usr/bin/env python3
"""Machine-produced evidence receipts: source, manifest, command, result and environment class.

Standard library only. Run from the repository with an isolated interpreter:

    python3 -I scripts/release/receipt.py run    --out DIR --name NAME --env mock|synthetic|live [--manifest PATH] [--timeout S] -- CMD...
    python3 -I scripts/release/receipt.py verify RECEIPT [--expect-live] [--check-source]

A receipt records what ran and what it returned; it does not interpret the result. ``live_proof`` is
derived, never declared: it is true only when the environment class is ``live``, no argument carries a
mock/fixture marker, the source tree is committed and clean, and the command exited 0. A mock or synthetic
run can never produce ``live_proof: true``, and ``verify`` rejects any receipt whose stored label disagrees
with its own contents or whose digest no longer matches.

Full command output is written to a log beside the receipt. The log is not embedded in the receipt and
must never be placed inside the repository (``--out`` inside the repository is refused).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_FILE = REPO_ROOT / "packaging" / "product.json"
VERSION_FILE = REPO_ROOT / "apps" / "api" / "version.py"

SCHEMA = "dashboard-evidence-receipt/v1"
ENV_CLASSES = ("mock", "synthetic", "live")
# Substring match, deliberately conservative: a false positive only downgrades a label, never upgrades one.
MOCK_MARKERS = ("mock", "fake", "stub", "fixture", "synthetic", "/usr/bin/false")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SECRET_ARG = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|authorization)\s*=")
VERSION = re.compile(r'__version__\s*=\s*"([^"]+)"')
MAX_TIMEOUT = 3600
DEFAULT_TIMEOUT = 600


class ReceiptError(Exception):
    pass


def die(message: str) -> None:
    raise ReceiptError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def minimal_env() -> dict[str, str]:
    passthrough = ("PATH", "HOME", "TMPDIR", "UV_CACHE_DIR", "npm_config_cache", "SSL_CERT_FILE")
    env = {k: os.environ[k] for k in passthrough if k in os.environ}
    env.update({"LC_ALL": "C", "TZ": "UTC"})
    return env


def redact_path(text: str) -> str:
    """Receipts are shared as evidence: show repository and home locations as placeholders."""
    return text.replace(str(REPO_ROOT), "<repo>").replace(str(Path.home()), "~")


def product_and_version() -> tuple[str, str]:
    try:
        product = json.loads(PRODUCT_FILE.read_text())["product"]
    except (OSError, ValueError, KeyError) as exc:
        die(f"cannot read product from {PRODUCT_FILE}: {exc}")
    match = VERSION.search(VERSION_FILE.read_text())
    if not match:
        die(f"no __version__ in {VERSION_FILE}")
    return product, match.group(1)


def git(*args: str) -> str:
    git_exe = shutil.which("git")
    result = subprocess.run([git_exe, *args], cwd=REPO_ROOT, env=minimal_env(), capture_output=True, text=True,
                            timeout=60)
    if result.returncode != 0:
        die(f"git {' '.join(args)} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def source_info() -> dict:
    """Commit and cleanliness of the source tree. Without a repository nothing is release-eligible."""
    if not shutil.which("git") or not (REPO_ROOT / ".git").exists():
        return {"commit": None, "dirty": None, "release_eligible": False}
    commit = git("rev-parse", "HEAD").strip()
    dirty = bool(git("status", "--porcelain", "--untracked-files=normal").strip())
    return {"commit": commit, "dirty": dirty, "release_eligible": not dirty}


def mock_markers(argv: list[str]) -> list[str]:
    found = []
    for arg in argv:
        lowered = arg.lower()
        found.extend(m for m in MOCK_MARKERS if m in lowered and m not in found)
    return found


def manifest_info(path: Path, source: dict) -> dict:
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as exc:
        die(f"cannot read manifest {path}: {exc}")
    commit = (manifest.get("source") or {}).get("commit")
    return {
        "name": path.name,
        "sha256": sha256_bytes(raw),
        "artifact_name": (manifest.get("artifact") or {}).get("name"),
        "artifact_sha256": (manifest.get("artifact") or {}).get("sha256"),
        "source_commit": commit,
        "source_commit_matches": None if commit is None or source["commit"] is None else commit == source["commit"],
    }


def run_step(argv: list[str], timeout: int, log_path: Path) -> dict:
    started, t0 = utc_now(), time.monotonic()
    timed_out, code = False, None
    try:
        result = subprocess.run(argv, cwd=REPO_ROOT, env=minimal_env(), capture_output=True, timeout=timeout)
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out, output = True, (exc.stdout or b"") + (exc.stderr or b"")
    except OSError as exc:
        output = str(exc).encode()
    duration = time.monotonic() - t0
    with log_path.open("xb") as handle:
        handle.write(output)
    status = "pass" if code == 0 and not timed_out else "fail"
    return {
        "argv": [redact_path(a) for a in argv],
        "exit_code": code,
        "timed_out": timed_out,
        "status": status,
        "started_at": started,
        "finished_at": utc_now(),
        "duration_s": round(duration, 3),
        "output_sha256": sha256_bytes(output),
        "output_bytes": len(output),
        "output_lines": output.count(b"\n"),
        "log": log_path.name,
    }


def build_receipt(*, name: str, env_class: str, argv: list[str], out_dir: Path, timeout: int = DEFAULT_TIMEOUT,
                  manifest: Path | None = None) -> tuple[Path, dict]:
    if not NAME.match(name):
        die(f"bad receipt name {name!r}")
    if env_class not in ENV_CLASSES:
        die(f"--env must be one of {ENV_CLASSES}")
    if not argv:
        die("no command given after --")
    if not 1 <= timeout <= MAX_TIMEOUT:
        die(f"timeout must be 1..{MAX_TIMEOUT} seconds")
    for arg in argv:
        if SECRET_ARG.search(arg):
            die("refusing to record a command argument that looks like a credential")
    out_dir = out_dir.resolve()
    if out_dir == REPO_ROOT or REPO_ROOT in out_dir.parents:
        die("--out must be outside the repository so evidence is never committed by accident")
    out_dir.mkdir(parents=True, exist_ok=True)

    source = source_info()
    product, version = product_and_version()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{name}-{stamp}"
    receipt_path, log_path = out_dir / f"{base}.json", out_dir / f"{base}.log"
    if receipt_path.exists() or log_path.exists():
        die(f"{receipt_path.name} already exists; choose another --name")

    started = utc_now()
    step = run_step(argv, timeout, log_path)
    markers = mock_markers(argv)
    live_proof = (env_class == "live" and not markers and source["commit"] is not None
                  and source["dirty"] is False and step["status"] == "pass")
    body = {
        "schema": SCHEMA,
        "name": name,
        "product": product,
        "version": version,
        "tool": "scripts/release/receipt.py",
        "started_at": started,
        "finished_at": utc_now(),
        "source": source,
        "manifest": manifest_info(manifest, source) if manifest else None,
        "environment": {
            "class": env_class,
            "mock_markers": markers,
            "host": {"system": platform.system(), "machine": platform.machine()},
        },
        "step": step,
        "overall": step["status"],
        "live_proof": live_proof,
    }
    body["receipt_sha256"] = sha256_bytes(canonical_json(body))
    with receipt_path.open("xb") as handle:
        handle.write(canonical_json(body))
    return receipt_path, body


def verify_receipt(path: Path, *, expect_live: bool = False, check_source: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [f"cannot read receipt: {exc}"], notes
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA}"], notes
    claimed = body.pop("receipt_sha256", None)
    if claimed != sha256_bytes(canonical_json(body)):
        errors.append("receipt_sha256 does not match the receipt contents")

    step = body["step"]
    env_class = body["environment"]["class"]
    expected_status = "pass" if step["exit_code"] == 0 and not step["timed_out"] else "fail"
    if step["status"] != expected_status:
        errors.append(f"step status {step['status']!r} contradicts exit_code {step['exit_code']!r}")
    if body["overall"] != step["status"]:
        errors.append("overall does not match the step status")
    markers = body["environment"]["mock_markers"]
    # Markers are taken from the raw argv at run time; the stored argv is redacted, so it can only show a subset.
    if not set(mock_markers(step["argv"])) <= set(markers):
        errors.append("recorded mock markers miss a marker still visible in the command arguments")
    source = body["source"]
    clean = source["commit"] is not None and source["dirty"] is False
    expected_live = env_class == "live" and not markers and clean and step["status"] == "pass"
    if body["live_proof"] is not expected_live:
        errors.append(f"live_proof must be {expected_live} for class {env_class!r}")
    if env_class != "live" and body["live_proof"]:
        errors.append(f"{env_class} run labelled as live proof")
    if expect_live and not body["live_proof"]:
        errors.append("not live proof")
    if check_source and source["commit"] is not None:
        current = source_info()
        if current["commit"] != source["commit"]:
            errors.append(f"stale receipt: recorded {source['commit']} but source is {current['commit']}")
        elif current["dirty"]:
            notes.append("source tree is dirty now; the receipt was made from the commit above")
    if not clean:
        notes.append("source is not a clean commit; this receipt is not release evidence")
    if env_class != "live":
        notes.append(f"environment class is {env_class}: a mock or synthetic result, not live proof")
    return errors, notes


def cmd_run(args: argparse.Namespace) -> int:
    argv = list(args.cmd)
    if argv and argv[0] == "--":
        argv = argv[1:]
    receipt_path, body = build_receipt(name=args.name, env_class=args.env, argv=argv, out_dir=Path(args.out),
                                       timeout=args.timeout,
                                       manifest=Path(args.manifest) if args.manifest else None)
    step = body["step"]
    print(f"{receipt_path}\n  overall {body['overall']} (exit {step['exit_code']}, {step['duration_s']}s)"
          f"\n  class {body['environment']['class']}  live_proof {str(body['live_proof']).lower()}"
          f"\n  source {body['source']['commit'] or 'none'}"
          f"{' (dirty)' if body['source']['dirty'] else ''}")
    return 0 if body["overall"] == "pass" else 1


def cmd_verify(args: argparse.Namespace) -> int:
    errors, notes = verify_receipt(Path(args.receipt), expect_live=args.expect_live, check_source=args.check_source)
    for note in notes:
        print(f"note: {note}")
    if errors:
        print("FAIL\n  " + "\n  ".join(errors))
        return 1
    print(f"OK {Path(args.receipt).name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one command and write its receipt")
    run.add_argument("--out", required=True, help="directory outside the repository for receipt and log")
    run.add_argument("--name", required=True)
    run.add_argument("--env", required=True, choices=ENV_CLASSES)
    run.add_argument("--manifest", help="release manifest to bind into the receipt")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    run.add_argument("cmd", nargs=argparse.REMAINDER, help="command after --")
    run.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify", help="check a receipt's digest, labels and consistency")
    verify.add_argument("receipt")
    verify.add_argument("--expect-live", action="store_true", help="fail unless the receipt is live proof")
    verify.add_argument("--check-source", action="store_true", help="fail if the source has moved since the run")
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ReceiptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
