"""What a project used, summed over every run of every task in it (planning included): time, tokens, models, and cost two ways.

* API-rate cost is what the tokens would cost at published API rates: the cost an agent reported, else the tokens priced from the catalog
  (the same derivation the run detail labels "derived"). It is the figure to compare routes with.
* Actual cost is what was charged for this work: nothing extra for a membership account or a free model, the API-rate cost otherwise.
  The billing mode is the one saved for each agent now, which is what the operator can check in Settings.
* Media is the Media studio's own ledger for the project folder: fal estimates for the images it generated, charged to the operator's fal
  account and counted in both figures.

Never stored: it is worked out from the run records and the media ledger each time, so it cannot drift from them."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

import billing
from models import ProjectTask, Run

PLANNING_ROLES = {'coordinate', 'plan', 'return plan', 'dispatch'}


def _run_costs(r, cfg, modes):
    model = r.model_reported or r.model_requested or ''
    if r.cost_usd is not None:
        api = r.cost_usd
    elif r.input_tokens is not None and r.output_tokens is not None:
        api, _ = billing.price({'model': model, 'ts': r.started_at, 'input_tokens': r.input_tokens, 'output_tokens': r.output_tokens,
                                'cached_input_tokens': r.cached_input_tokens, 'cache_write_tokens': r.cache_write_tokens}, cfg)
    else:
        api = None
    if billing.is_free(model):
        billed = 'free'
    elif modes.get(r.agent) == 'subscription':
        billed = 'membership'
    else:
        billed = 'api'
    actual = 0.0 if billed in {'free', 'membership'} else api
    return model, billed, api, actual


def _media(settings, working_dir):
    """Generated images for this project folder, from the Media studio ledger: count and fal estimate."""
    import media_generate
    if not working_dir:
        return {'images': 0, 'estimate_usd': 0.0, 'unpriced': 0}
    try:
        root = Path(working_dir).expanduser().resolve()
        rows = media_generate.Ledger(Path(settings.data_dir) / 'media' / 'ledger.jsonl').rows(limit=100_000)
    except OSError:
        return {'images': 0, 'estimate_usd': 0.0, 'unpriced': 0}
    done = []
    for row in rows:
        try:
            folder = Path(str(row.get('folder') or '')).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if row.get('status') == 'done' and (folder == root or root in folder.parents):
            done.append(row)
    priced = [row['estimate_usd'] for row in done if isinstance(row.get('estimate_usd'), (int, float))]
    return {'images': len(done), 'estimate_usd': round(sum(priced), 4), 'unpriced': len(done) - len(priced)}


def _bucket():
    return {'runs': 0, 'succeeded': 0, 'duration_s': 0.0, 'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0,
            'api_usd': 0.0, 'api_unpriced': 0, 'actual_usd': 0.0, 'actual_unpriced': 0}


def _add(b, r, api, actual):
    b['runs'] += 1
    b['succeeded'] += r.stage == 'succeeded'
    b['duration_s'] += r.duration_s or 0
    b['input_tokens'] += r.input_tokens or 0
    b['output_tokens'] += r.output_tokens or 0
    b['cached_input_tokens'] += r.cached_input_tokens or 0
    if api is None:
        b['api_unpriced'] += 1
    else:
        b['api_usd'] += api
    if actual is None:
        b['actual_unpriced'] += 1
    else:
        b['actual_usd'] += actual


def _round(b):
    return {**b, 'duration_s': round(b['duration_s'], 1), 'api_usd': round(b['api_usd'], 4), 'actual_usd': round(b['actual_usd'], 4)}


def totals(s, p, settings, working_dir=None) -> dict | None:
    """Totals for one project, or None before any of its tasks has run."""
    rows = list(s.execute(select(Run, ProjectTask.role).join(ProjectTask, ProjectTask.card_id == Run.card_id)
                          .where(ProjectTask.project_id == p.id, Run.stage.not_in(('queued', 'running', 'awaiting_approval')))))
    if not rows:
        return None
    cfg = billing.config(s)
    modes = {agent: billing.account_mode(s, agent) for agent in {r.agent for r, _ in rows}}
    total, planning, stories = _bucket(), _bucket(), _bucket()
    models = defaultdict(_bucket)
    labels = {}
    for r, role in rows:
        model, billed, api, actual = _run_costs(r, cfg, modes)
        for b in (total, planning if role in PLANNING_ROLES else stories, models[(r.agent, model)]):
            _add(b, r, api, actual)
        labels[(r.agent, model)] = {'agent': r.agent, 'model': model, 'billed': billed,
                                    'model_derived': labels.get((r.agent, model), {}).get('model_derived', False) or not r.model_reported}
    starts = [r.started_at for r, _ in rows if r.started_at]
    ends = [r.ended_at for r, _ in rows if r.ended_at]
    media = _media(settings, working_dir)
    out = _round(total)
    out.update({
        'planning': _round(planning), 'stories': _round(stories),
        'elapsed_s': (max(ends) - min(starts)) if starts and ends else None,
        'models': sorted(({**labels[k], **_round(b)} for k, b in models.items()), key=lambda m: (-m['runs'], m['agent'], m['model'])),
        'media': media,
        'total_api_usd': round(total['api_usd'] + media['estimate_usd'], 4),
        'total_actual_usd': round(total['actual_usd'] + media['estimate_usd'], 4),
        'billing_note': 'Actual cost counts membership and free-model runs as $0 and API runs at their reported or derived cost, '
                        'using the billing mode saved for each agent now. API-rate cost prices every run at published API rates. '
                        'Media is the Media studio fal estimate. Estimates, not invoices.',
    })
    return out
