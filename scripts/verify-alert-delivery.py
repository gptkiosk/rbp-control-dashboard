#!/usr/bin/env python3
"""Force one disposable local run to fail and verify one durable alert (opt-in live send)."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
import agents
from alerts import AlertMonitor, HermesSender, run_message
from db import make_engine, make_session_factory
from dispatcher import Dispatcher
from migrate import upgrade_to_head
from models import AlertEvent, Card, Run
from sqlalchemy import select

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--destination", required=True, help="Explicit discord:CHANNEL_ID")
parser.add_argument("--send", action="store_true", help="Actually send the one test notification through Hermes")
args = parser.parse_args()

with tempfile.TemporaryDirectory(prefix="mcd-alert-test-") as name:
    root = Path(name)
    engine = make_engine(root / "data.db")
    upgrade_to_head(engine)
    sessions = make_session_factory(engine)
    rules = root / "alerts.toml"
    def write_rules(delivery):
        rules.write_text(f'enabled = true\ndelivery_enabled = {str(delivery).lower()}\ndestination = {json.dumps(args.destination)}\n')
        rules.chmod(0o600)
    write_rules(False)
    def simulate(target, message): return "1525000000000000000"
    sender = HermesSender(str(Path.home()/".local"/"bin"/"hermes")) if args.send else simulate
    monitor = AlertMonitor(sessions, rules, sender)
    monitor.tick()
    assert monitor.error is None, "Invalid alert destination"
    settings = SimpleNamespace(runs_dir=root/"runs", max_concurrent_runs=1, default_budget_usd=1,
                               claude_path=sys.executable, run_retention_days=90)
    def build(card, prompt, model, budget, binary): return [sys.executable, "-c", "import sys; sys.exit(23)"]
    registry = {"mcd-test": agents.AgentSpec("mcd-test", "MCD test", "worker", "claude_path", build, agents.Parser)}
    now=int(time.time())
    with sessions.begin() as s:
        card=Card(title="Disposable MCD alert verification",body="Local verification only",agent="mcd-test",mode="read",working_dir=str(root),column="queued",position=1,timeout_s=30,needs_approval=False,created_by="operator",created_at=now,updated_at=now)
        s.add(card)
    dispatcher=Dispatcher(sessions,settings,registry=registry)
    async def drain():
        await dispatcher.tick()
        while dispatcher._tasks:
            await asyncio.gather(*list(dispatcher._tasks.values()),return_exceptions=True)
    asyncio.run(drain())
    monitor.tick()
    with sessions.begin() as s:
        run=s.scalar(select(Run))
        assert run.stage=="failed" and run.exit_code==23
        event=s.scalar(select(AlertEvent))
        event.message=run_message(run,test=True)
        message=event.message
    write_rules(True)
    monitor.tick()
    monitor.tick()
    restarted=AlertMonitor(sessions,rules,sender)
    restarted.tick()
    events=restarted.status()["events"]
    assert len(events)==1, "Expected one alert record"
    event=events[0]
    result={"live_send":args.send,"destination":args.destination,"message":message,"status":event["status"],"message_id":event["message_id"],"sent_at":event["sent_at"],"event_count":len(events),"error":event["error"]}
    print(json.dumps(result,indent=2))
    engine.dispose()
    if event["status"]!="sent": raise SystemExit(1)
