"""A run that already carries a human decision is never silently rerun after a restart."""
import asyncio
import json
import time

import pytest
from sqlalchemy import select

from models import Card, Run
from tests.test_dispatcher import _card
from tests.test_human_gates import decision, setup


@pytest.mark.parametrize("checkpoint_key", ["decisions", "pending_decision"])
def test_decided_run_lost_in_restart_is_not_requeued(sessions, tmp_path, checkpoint_key):
    d, adapter = setup(sessions, tmp_path)  # no adapter state file: nothing to reattach
    cid = _card(sessions, tmp_path, "prompt", column="running", model="pinned-model")
    value = {"gate-1": decision(1)} if checkpoint_key == "decisions" else decision(1)
    with sessions.begin() as s:
        card = s.get(Card, cid)
        card.idempotency_key = "rcd:exec:test"
        s.add(Run(card_id=cid, agent="fake", stage="running", started_at=int(time.time()),
                  working_dir=str(tmp_path), command="[]", log_path="", model_requested="pinned-model",
                  idempotency_key="rcd:exec:test", attempt=1,
                  checkpoint=json.dumps({checkpoint_key: value})))
    assert asyncio.run(d.tick()) == 0
    with sessions() as s:
        runs = list(s.scalars(select(Run).where(Run.card_id == cid)))
        assert len(runs) == 1 and runs[0].stage == "interrupted"
        assert runs[0].model_requested == "pinned-model"
        assert s.get(Card, cid).column == "failed"
    assert adapter.starts == 0
