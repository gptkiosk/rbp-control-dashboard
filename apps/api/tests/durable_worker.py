"""Disposable dispatcher host and synthetic runtime for real SIGKILL tests.

No server socket, runtime binary, credential, or outbound call is involved.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents import AgentSpec, Parser
from db import make_engine, make_session_factory
from dispatcher import Dispatcher
from models import Card, Run
from sqlalchemy import select
import project_outputs


def runtime(root):
    key = os.environ['RCD_IDEMPOTENCY_KEY']
    project_outputs.save(SimpleNamespace(data_dir=root), 1, 1, 1, 'synthetic', 'one artifact')
    (root / 'receipt.json').write_text(json.dumps(dict(response_id='synthetic:' + key,
        model='synthetic:free', ts=1, cost_usd=0, usage=dict(input_tokens=1, output_tokens=1))))
    (root / 'runtime.pid').write_text(str(os.getpid()))
    while not (root / 'release').exists():
        time.sleep(.02)
    print(json.dumps(dict(text='OK')), flush=True)


class SyntheticParser(Parser):
    def feed(self, line):
        self.meta.result_text = json.loads(line)['text']
        self.meta.cost_usd = 0
        return ['completed']


async def host(root):
    sessions = make_session_factory(make_engine(root / 'test.db'))
    settings = SimpleNamespace(runs_dir=root / 'runs', max_concurrent_runs=1,
        default_budget_usd=0, claude_path=sys.executable, run_retention_days=90)
    def build(card, prompt, model, budget, binary):
        return [sys.executable, str(Path(__file__).resolve()), 'runtime', str(root)]
    registry = {'synthetic': AgentSpec('synthetic', 'Synthetic', 'worker', 'claude_path', build, SyntheticParser)}
    dispatcher = Dispatcher(sessions, settings, registry=registry)
    while True:
        await dispatcher.tick()
        with sessions() as db:
            card = db.get(Card, 1)
            running = db.scalar(select(Run).where(Run.stage == 'running'))
            done = card.column == 'done'
        if running and (root / 'receipt.json').exists():
            dispatcher._adapter_event(running.id, 'synthetic', dict(type='usage',
                data=dict(provider_receipts=[json.loads((root / 'receipt.json').read_text())])))
        if done:
            (root / 'done').touch()
            return
        await asyncio.sleep(.02)


if __name__ == '__main__':
    root = Path(sys.argv[2])
    if sys.argv[1] == 'runtime':
        runtime(root)
    else:
        asyncio.run(host(root))
