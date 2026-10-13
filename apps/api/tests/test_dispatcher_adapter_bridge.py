"""An additional runtime plugs into dispatch without replacing workflow code."""
import asyncio
from types import SimpleNamespace

from adapter_contract import AgentAdapter, SCHEMA_VERSION
from agents import AgentSpec, Parser
from dispatcher import Dispatcher
from models import Card, Run
from sqlalchemy import select


class StubAdapter:
    name = "pi-stub"

    def __init__(self):
        self.specs = []
        self.recovered = False

    def capabilities(self):
        return {}

    async def start(self, spec):
        assert self.recovered
        self.specs.append(spec)
        return dict(run_id=spec["run_id"], status="running", replayed=False)

    async def events(self, run_id, after_seq=0):
        yield dict(schema_version=SCHEMA_VERSION, run_id=run_id, seq=1, ts=1,
                   type="status", data=dict(to="succeeded", **{"from": "running"}))

    async def result(self, run_id):
        return dict(status="succeeded", model=dict(reported="assigned", provider="synthetic"),
                    session=dict(session_id="pi-session"), result_text="handoff",
                    cost=dict(usd=0.0), usage=dict(input_tokens=12, output_tokens=3),
                    exit_code=0, error=None, duration_s=1.0)

    async def cancel(self, request):
        return dict(run_id=request["run_id"], status="cancelled", replayed=False)

    async def resume(self, decision):
        raise AssertionError("workflow did not ask to resume")

    async def heartbeat(self, run_id):
        return {}

    async def recover(self):
        self.recovered = True
        return []


def test_additional_adapter_keeps_claim_and_finish_behavior(sessions, tmp_path):
    adapter = StubAdapter()
    assert isinstance(adapter, AgentAdapter)
    agent = AgentSpec(adapter.name, "Synthetic Pi runtime", "worker", "claude_path",
                      lambda *args: ["never-launched"], Parser)
    settings = SimpleNamespace(runs_dir=tmp_path / "runs", max_concurrent_runs=1,
                               default_budget_usd=1.0, claude_path="/unused",
                               dispatch_route_classes={"pi-stub||assigned": "free"})
    dispatcher = Dispatcher(sessions, settings, registry={adapter.name: agent},
                            adapters={adapter.name: adapter})
    with sessions.begin() as db:
        card = Card(title="synthetic", body="assigned prompt", agent=adapter.name,
                    model="assigned", mode="read", working_dir=str(tmp_path),
                    column="queued", position=1, timeout_s=30, needs_approval=False,
                    created_by="test", created_at=1, updated_at=1)
        db.add(card)
        db.flush()
        cid = card.id
    async def run():
        assert await dispatcher.tick() == 1
        await asyncio.gather(*dispatcher._tasks.values())
    asyncio.run(run())
    with sessions() as db:
        row = db.scalar(select(Run).where(Run.card_id == cid))
        assert db.get(Card, cid).column == "done"
        assert (row.stage, row.model_requested, row.model_reported, row.result_text) == (
            "succeeded", "assigned", "assigned", "handoff")
        assert (row.input_tokens, row.output_tokens, row.cost_usd) == (12, 3, 0.0)
    assert len(adapter.specs) == 1
    spec = adapter.specs[0]
    assert spec["prompt"] == "assigned prompt"
    assert spec["workspace"] == dict(path=str(tmp_path), mode="read")
    assert spec["model_policy"]["assigned"]["model"] == "assigned"


def test_stop_preserves_interrupted_rows_and_stops_only_owned_process(sessions, tmp_path):
    from tests.test_dispatcher import _card, _registry, _settings
    dispatcher = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, "import time; time.sleep(30)")
    async def run():
        await dispatcher.tick()
        while not next(iter(dispatcher._handles.values())).proc:
            await asyncio.sleep(0.001)
        proc = next(iter(dispatcher._handles.values())).proc
        await dispatcher.stop()
        assert proc.returncode is not None
    asyncio.run(run())
    with sessions() as db:
        row = db.scalar(select(Run).where(Run.card_id == cid))
        assert row.stage == "interrupted"
        assert db.get(Card, cid).column == "queued"
        assert db.get(Card, cid).idempotency_key == row.idempotency_key
