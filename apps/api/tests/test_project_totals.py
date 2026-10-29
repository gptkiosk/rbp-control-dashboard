import json
from pathlib import Path

from sqlalchemy import select

import billing
from models import ProjectTask, Run
from tests.test_projects import active, app, node  # noqa: F401  (fixture)


def add_run(db, card_id, agent, model, *, reported=None, cost=None, tokens=(1_000_000, 100_000), duration=60, started=1_800_000_000):
    db.add(Run(card_id=card_id, agent=agent, model_requested=model, model_reported=reported, stage='succeeded', started_at=started,
               ended_at=started + duration, duration_s=duration, input_tokens=tokens[0], output_tokens=tokens[1], cost_usd=cost,
               working_dir='/tmp', command='[]', log_path='test-only'))


def test_completed_project_totals_split_actual_and_api_rate_cost(app):
    """Operator 2026-10-29: a finished project should show its time, tokens, models and cost, with membership use next to its API-rate cost."""
    c, sessions, wd, settings = app
    p = active(app, [node('a'), node('b', depends_on=['a'])])
    with sessions.begin() as db:
        story = db.scalar(select(ProjectTask.card_id).where(ProjectTask.project_id == p['id'], ProjectTask.role == 'story'))
        planning = db.scalars(select(Run).join(ProjectTask, ProjectTask.card_id == Run.card_id).where(ProjectTask.project_id == p['id'])).all()
        for r in planning:   # the planning run the fixture made: give it nothing to price
            r.input_tokens = r.output_tokens = None; r.duration_s = 30
        add_run(db, story, 'codex', 'gpt-6.1-sol')                                    # membership: tokens only, as Codex reports
        add_run(db, story, 'claude', 'claude-sonnet-5-5', reported='claude-sonnet-5-5', cost=0.5)   # membership, reported API equivalent
        add_run(db, story, 'grok', 'gpt-6.1-sol', reported='gpt-6.1-sol')              # an API account: charged
        add_run(db, story, 'hermes', 'openrouter/free', tokens=(10, 10))               # free model
    ledger = Path(settings.data_dir) / 'media' / 'ledger.jsonl'
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('\n'.join(json.dumps(r) for r in [
        {'status': 'done', 'folder': str(wd), 'estimate_usd': 0.12, 'slot': 'hero'},
        {'status': 'failed', 'folder': str(wd), 'estimate_usd': 0.12, 'slot': 'hero'},
        {'status': 'done', 'folder': str(wd.parent / 'elsewhere'), 'estimate_usd': 5.0, 'slot': 'x'}]) + '\n')

    t = c.get(f"/api/projects/{p['id']}").json()['totals']
    sol, _ = billing.price({'model': 'gpt-6.1-sol', 'ts': 1_800_000_000, 'input_tokens': 1_000_000, 'output_tokens': 100_000}, {'rates': billing.DEFAULT_RATES})
    assert sol and sol > 0
    assert t['runs'] == len(planning) + 4
    assert t['input_tokens'] == 3_000_010 and t['output_tokens'] == 300_010
    assert t['stories']['runs'] == 4 and t['planning']['runs'] == len(planning)
    assert abs(t['api_usd'] - round(2 * sol + 0.5, 4)) < 1e-3                         # every priced run at API rates
    assert abs(t['actual_usd'] - round(sol, 4)) < 1e-3                                # only the API-account run is charged
    assert t['media'] == {'images': 1, 'estimate_usd': 0.12, 'unpriced': 0}
    assert abs(t['total_actual_usd'] - round(sol + 0.12, 4)) < 1e-3
    rows = {(m['agent'], m['model']): m for m in t['models']}
    assert rows[('codex', 'gpt-6.1-sol')]['billed'] == 'membership' and rows[('codex', 'gpt-6.1-sol')]['model_derived']
    assert rows[('codex', 'gpt-6.1-sol')]['actual_usd'] == 0 and rows[('codex', 'gpt-6.1-sol')]['api_usd'] > 0
    assert rows[('claude', 'claude-sonnet-5-5')]['billed'] == 'membership' and not rows[('claude', 'claude-sonnet-5-5')]['model_derived']
    assert rows[('grok', 'gpt-6.1-sol')]['billed'] == 'api'
    assert rows[('hermes', 'openrouter/free')]['billed'] == 'free' and rows[('hermes', 'openrouter/free')]['api_usd'] == 0


def test_a_project_with_no_finished_runs_has_no_totals(app):
    c, sessions, wd, settings = app
    p = c.post('/api/projects', json={'title': 'Draft', 'brief': 'Build it.', 'working_dir': str(wd), 'nodes': []}).json()
    assert c.get(f"/api/projects/{p['id']}").json()['totals'] is None
