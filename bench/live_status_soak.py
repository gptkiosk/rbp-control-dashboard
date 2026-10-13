#!/usr/bin/env python3
"""Soak test for live status streaming (apps/api/live_status.py) on a Pi.

Starts its own disposable API on a loopback port (never 8800) with a fresh temporary data
dir, the collector and dispatcher off and sign-in off. It then:
  - keeps --clients SSE streams open on /api/events/stream, reconnecting like a browser;
  - moves synthetic human-assigned task cards between columns every --interval seconds and
    measures the delay from the committed PATCH to each client seeing the change;
  - samples the API's RSS every --sample seconds;
  - optionally restarts the API every --restart-every seconds (SIGTERM, same port) and
    measures how long clients take to reconnect and receive a `reset`.
It stops only the process it started. Standard library only; run from the repo root:

    apps/api/.venv/bin/python bench/live_status_soak.py --duration 3600 --out soak.json

Pass criteria (story S3_live_status): max delay < 2 s with no missed changes, every client
reconnects after each restart, and RSS grows less than RSS_GROWTH_LIMIT_KIB after warm-up
(the event ring is fixed-size). Exit status 0 = pass, 1 = fail.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "apps" / "api"
COLUMNS = ["backlog", "queued", "running", "review", "done"]
RSS_GROWTH_LIMIT_KIB = 16 * 1024  # allocator noise; a leak per event would far exceed this in an hour


def free_port(preferred: int) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 50)]:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free loopback port near %d" % preferred)


class Api:
    """The disposable API process this tool owns."""

    def __init__(self, port: int, data: Path, python: str):
        self.port, self.data, self.python = port, data, python
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        (self.data / "ws" / "proj").mkdir(parents=True, exist_ok=True)
        env = {**os.environ,
               "MAC_CONTROL_PORT": str(self.port), "MAC_CONTROL_HOST": "127.0.0.1",
               "MAC_CONTROL_DATA_DIR": str(self.data / "data"),
               "MAC_CONTROL_WEB_DIST": str(self.data / "no-dist"),
               "MAC_CONTROL_COLLECTOR_ENABLED": "false", "MAC_CONTROL_DISPATCHER_ENABLED": "false",
               "MAC_CONTROL_AUTH_ENABLED": "false",
               # Settings also read ~/.mac-control/.env: pin anything that could alert or send.
               "MAC_CONTROL_ALERTS_CONFIG_PATH": str(self.data / "alerts.toml"),
               "MAC_CONTROL_HERMES_PATH": str(self.data / "no-hermes"),
               "MAC_CONTROL_WORKDIR_ROOTS": json.dumps([str(self.data / "ws")])}
        self.proc = subprocess.Popen([self.python, "serve.py"], cwd=API, env=env,
                                     stdout=subprocess.DEVNULL, stderr=open(self.data / "api.log", "ab"))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                request(self.port, "GET", "/healthz")
                return
            except OSError:
                time.sleep(0.2)
        raise SystemExit("API did not start; see %s" % (self.data / "api.log"))

    def stop(self) -> float:
        """SIGTERM our own process; returns seconds until it exited."""
        if not self.proc or self.proc.poll() is not None:
            return 0.0
        started = time.monotonic()
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        return time.monotonic() - started

    def rss_kib(self) -> int | None:
        try:
            for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except (OSError, AttributeError):
            pass
        try:  # macOS / no /proc
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(self.proc.pid)], capture_output=True, text=True)
            return int(out.stdout.strip() or 0) or None
        except (OSError, ValueError):
            return None


def request(port: int, method: str, path: str, body: dict | None = None) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"Content-Type": "application/json", "X-Mac-Control": "1"})
        res = conn.getresponse()
        data = res.read()
        if res.status >= 400:
            raise RuntimeError(f"{method} {path}: {res.status} {data[:200]!r}")
        return json.loads(data) if data else {}
    finally:
        conn.close()


class Client(threading.Thread):
    """A browser-like SSE client: reconnects after `retry` ms and sends Last-Event-ID."""

    def __init__(self, port: int, seen: dict, lock: threading.Lock, index: int):
        super().__init__(daemon=True)
        self.port, self.seen, self.lock, self.index = port, seen, lock, index
        self.last_id = ""
        self.retry_s = 1.0
        self.boots: list[tuple[float, str, bool]] = []
        self.running = True

    def run(self) -> None:
        while self.running:
            try:
                self._stream()
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(self.retry_s)

    def _stream(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {"Accept": "text/event-stream"}
        if self.last_id:
            headers["Last-Event-ID"] = self.last_id
        conn.request("GET", "/api/events/stream", headers=headers)
        res = conn.getresponse()
        frame: dict[str, str] = {}
        while self.running:
            line = res.fp.readline()
            if not line:
                return
            line = line.decode().rstrip("\n")
            if line:
                key, _, value = line.partition(": ")
                frame[key] = value
                continue
            self._handle(frame)
            frame = {}

    def _handle(self, frame: dict[str, str]) -> None:
        now = time.monotonic()
        if "retry" in frame:
            self.retry_s = int(frame["retry"]) / 1000
        if frame.get("id"):
            self.last_id = frame["id"]
        kind = frame.get("event")
        data = json.loads(frame["data"]) if "data" in frame else {}
        if kind == "hello":
            self.boots.append((now, data["boot"], data["reset"]))
        elif kind == "status" and data.get("type") == "card" and data.get("change") == "updated":
            with self.lock:  # latest sighting; a card revisits a column once per cycle
                self.seen[(data["card_id"], data["column"], self.index)] = now


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=float, default=3600)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--cards", type=int, default=20)
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between card moves")
    ap.add_argument("--sample", type=float, default=60, help="seconds between RSS samples")
    ap.add_argument("--restart-every", type=float, default=900, help="0 disables restarts")
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--out", type=Path, default=Path("live-status-soak.json"))
    args = ap.parse_args()
    if args.port == 8800:
        raise SystemExit("8800 belongs to the live service; use another port")

    seen: dict = {}
    lock = threading.Lock()
    with tempfile.TemporaryDirectory(prefix="rcd-soak-") as tmp:
        api = Api(free_port(args.port), Path(tmp), args.python)
        api.start()
        clients = [Client(api.port, seen, lock, i) for i in range(args.clients)]
        for c in clients:
            c.start()
        cards = [request(api.port, "POST", "/api/cards", {"title": f"soak {i}", "body": "synthetic",
                                                          "assignee_type": "human"})["id"]
                 for i in range(args.cards)]
        sent: list[tuple[int, str, float]] = []
        rss: list[tuple[float, int, int | None]] = []
        restarts: list[dict] = []
        started = time.monotonic()
        next_sample = next_restart = started
        if args.restart_every:
            next_restart = started + args.restart_every
        step = 0
        try:
            while (now := time.monotonic()) - started < args.duration:
                if now >= next_sample:
                    rss.append((round(now - started, 1), api.proc.pid, api.rss_kib()))
                    next_sample += args.sample
                if args.restart_every and now >= next_restart:
                    before = {c.index: len(c.boots) for c in clients}
                    stop_s = api.stop()
                    api.start()
                    up = time.monotonic()
                    while time.monotonic() - up < 30 and any(len(c.boots) == before[c.index] for c in clients):
                        time.sleep(0.05)
                    restarts.append({"at_s": round(now - started, 1), "shutdown_s": round(stop_s, 2),
                                     "reconnected": sum(len(c.boots) > before[c.index] for c in clients),
                                     "clients": len(clients),
                                     "reconnect_s": [round(c.boots[-1][0] - up, 2) for c in clients
                                                     if len(c.boots) > before[c.index]],
                                     "all_reset": all(c.boots[-1][2] for c in clients if c.boots)})
                    next_restart += args.restart_every
                card = cards[step % len(cards)]
                column = COLUMNS[(step // len(cards) + 1) % len(COLUMNS)]
                request(api.port, "PATCH", f"/api/cards/{card}", {"column": column})
                sent.append((card, column, time.monotonic()))
                step += 1
                time.sleep(args.interval)
            time.sleep(3)
        finally:
            for c in clients:
                c.running = False
            api.stop()

    delays, missed = [], 0
    # A card revisits a column every len(COLUMNS) * cards moves; only the latest send counts.
    latest = {}
    for card, column, at in sent:
        latest[(card, column)] = at
    for (card, column), at in latest.items():
        for c in clients:
            got = seen.get((card, column, c.index))
            if got is None or got < at - 0.001:
                missed += 1
            else:
                delays.append(got - at)
    # Flatness is judged per API process (a restart starts a new one), after its first quarter.
    warm: list[int] = []
    growth = 0
    for pid in dict.fromkeys(p for _, p, _ in rss):
        values = [v for _, p, v in rss if p == pid and v]
        values = values[len(values) // 4:]
        warm += values
        growth = max(growth, (values[-1] - min(values)) if values else 0)
    report = {
        "duration_s": args.duration, "clients": args.clients, "moves": len(sent),
        "delay_s": {"p50": percentile(delays, 50), "p95": percentile(delays, 95),
                    "max": max(delays) if delays else None, "samples": len(delays), "missed": missed},
        "rss_kib": {"samples": rss, "min_after_warmup": min(warm) if warm else None,
                    "max_after_warmup": max(warm) if warm else None, "growth_after_warmup": growth},
        "restarts": restarts,
    }
    report["pass"] = bool(delays and report["delay_s"]["max"] < 2 and missed == 0
                          and growth < RSS_GROWTH_LIMIT_KIB
                          and all(r["reconnected"] == r["clients"] for r in restarts))
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "rss_kib"} | {
        "rss_kib": {k: v for k, v in report["rss_kib"].items() if k != "samples"}}, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
