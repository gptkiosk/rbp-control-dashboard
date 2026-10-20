"""Operator-owned recovery routes and bounded, local route telemetry.

No prompt, credential, account identity or raw provider error is returned here.
Availability and observed process success are not proof of task correctness.
"""
import json
import re
import time
from collections import defaultdict
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from project_schemas import Route


class RecoveryPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    apply_to_stories: bool = False
    routes: list[Route] = Field(default_factory=list, max_length=6)

    @field_validator('routes')
    @classmethod
    def unique(cls, routes):
        if len({(r.agent, r.model) for r in routes}) != len(routes):
            raise ValueError('Choose each recovery route once.')
        for route in routes:
            if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', route.model):
                raise ValueError('Use a model ID without spaces or control characters.')
        return routes


def failure_kind(run, contract_failed=False):
    if contract_failed:
        return 'invalid_output'
    if run.stage == 'succeeded':
        return None
    if run.stage == 'timeout':
        return 'timeout'
    value = (run.error or '')[:8000]
    # Only the taxonomy/code or error text is examined; result text may be a project artifact.
    if re.search(r'FREE_ONLY|PRICE_UNKNOWN|BUDGET_|ROUTE_UNPINNED|APPROVAL|permission|denied|sandbox', value, re.I):
        return 'policy'
    if re.search(r'authentication|unauthorized|invalid.api.key|sign.?in|log.?in|\b401\b|\b403\b', value, re.I):
        return 'sign_in'
    if re.search(r'rate.?limit|quota|usage.limit|session.limit|too many requests|\b429\b', value, re.I):
        return 'rate_limit'
    if re.search(r'provider|overload|unavailable|temporar|connection|network|\b50[234]\b', value, re.I):
        return 'provider'
    return 'execution'


def stats(s, window_s=7 * 86400):
    from models import Run, RunEvent
    runs = list(s.scalars(select(Run).where(Run.started_at >= int(time.time()) - window_s,
        Run.stage.in_(['succeeded', 'failed', 'timeout'])).order_by(Run.id.desc()).limit(500)))
    ids = [r.id for r in runs]
    bad = set(s.scalars(select(RunEvent.run_id).where(RunEvent.run_id.in_(ids),
        RunEvent.kind == 'contract_failure'))) if ids else set()
    grouped = defaultdict(list)
    for run in runs:
        grouped[(run.agent, run.model_requested or '')].append(failure_kind(run, run.id in bad))
    result = []
    for (agent, model), outcomes in grouped.items():
        recent = outcomes[:5]
        route_failures = sum(v in {'invalid_output', 'rate_limit', 'provider', 'timeout'} for v in recent)
        persistent = len(recent) >= 3 and route_failures >= 3
        result.append({'agent': agent, 'model': model, 'attempts': len(outcomes),
            'failures': sum(v is not None for v in outcomes), 'recent_failures': route_failures,
            'persistent': persistent, 'last_failure': outcomes[0],
            'categories': {kind: outcomes.count(kind) for kind in sorted({v for v in outcomes if v})}})
    return result


def options(s, settings):
    from agents import REGISTRY
    from dispatch_gate import reviewed_route_class
    import native_routes
    import projects
    native = native_routes.read(settings)
    candidates = []
    for agent in ('claude', 'codex', 'grok'):
        if agent in {'claude','codex'} or projects.subscription(s, agent):
            models = [projects.subscription_model(agent, 50), projects.subscription_model(agent, 50, planner=True),
                      REGISTRY[agent].default_model()]
            # Grok is not a Claude/Codex subscription tier.
            if agent == 'grok':
                models = [REGISTRY[agent].default_model()]
            candidates.extend({'agent': agent, 'model': m} for m in models if m)
    for agent, config in native.items():
        candidates.extend({'agent': agent, 'model': m} for m in config.get('models', []))
    seen = set()
    result = []
    for route in candidates:
        key = (route['agent'], route['model'])
        if key in seen:
            continue
        seen.add(key)
        installed = REGISTRY[route['agent']].available(settings)
        price = reviewed_route_class(s, settings, SimpleNamespace(agent=route['agent'], agent_target=''), route['model'])
        allowed = installed and price in {'free', 'subscription', 'paid'} and allowed_class(s, settings, price)
        cost = {'free': 'Free endpoint; availability and limits vary.',
                'subscription': 'Uses membership quota; account limits and any enabled overage still apply.',
                'paid': 'Bills your provider API account. Membership does not cover these charges.'}.get(price,
                    'Price is not reviewed. Configure its billing class before using automatic recovery.')
        if route['agent']=='hermes' and any(m and not m.endswith(':free') and m not in {'openrouter/free','openrouter/openrouter/free'} for m in native.get('hermes',{}).get('models',[])):
            cost += ' Hermes native provider fallbacks may add charges; review its configuration.'
        if price is None and route['agent'] in {'claude','codex'}:
            cost='Configure your membership or API billing mode in Billing & rates before using this route.'
        result.append({**route, 'price_class': price or 'unknown', 'installed': installed,
            'allowed': bool(allowed), 'cost': cost})
    return result


def allowed_class(s, settings, price):
    import billing
    return not settings.dispatch_free_only or price == 'free' or (
        price == 'subscription' and billing.limits(s, settings).get('allow_subscription_in_free_only', False)) or (
        price == 'paid' and billing.limits(s, settings).get('allow_paid_in_free_only', False))


def policy(s, owner):
    import profiles
    return profiles.prefs(s, owner).route_recovery


def eligible(s, settings, owner, *, paid_approved=False):
    from dispatch_gate import resolve_free_alias
    saved = policy(s, owner)
    if not saved.enabled:
        return []
    current = {(r['agent'], r['model']): r for r in options(s, settings)}
    result = []
    health = {(r['agent'], r['model']): r for r in stats(s)}
    for route in saved.routes:
        key = (route.agent, route.model)
        item = current.get(key)
        if item and item['allowed'] and (item['price_class'] != 'paid' or paid_approved):
            result.append({'agent':route.agent,'model':resolve_free_alias(s,settings,route.agent,None,route.model) or route.model})
    result=list({(r['agent'],r['model']):r for r in result}.values())
    # Preserve operator order within each group. A working alternative is tried before a persistently failing route.
    return sorted(result, key=lambda r: bool(health.get((r['agent'], r['model']), {}).get('persistent')))


def payload(s, settings, owner):
    saved = policy(s, owner)
    health = stats(s)
    recommendations = []
    for item in health:
        if item['persistent']:
            recommendations.append({'agent': item['agent'], 'model': item['model'],
                'message': f"{item['recent_failures']} of its last {min(item['attempts'], 5)} attempts had provider, timeout or output failures. A different route may be needed.",
                'cost': 'A membership route uses your quota. A paid API route adds provider charges; free endpoints may still be unavailable.',
                'link': '/profile#route-recovery'})
    return {'policy': saved.model_dump(), 'options': options(s, settings), 'health': health,
        'recommendations': recommendations, 'window_days': 7, 'sample_limit': 500,
        'host_free_only': settings.dispatch_free_only,
        'subscription_allowed': allowed_class(s, settings, 'subscription'),
        'paid_allowed': allowed_class(s,settings,'paid')}


def contract_failure(s, run):
    from models import RunEvent
    if not s.scalar(select(RunEvent.id).where(RunEvent.run_id == run.id, RunEvent.kind == 'contract_failure')):
        s.add(RunEvent(run_id=run.id, ts=int(time.time()), kind='contract_failure', text='Output failed the planning contract.'))
        s.add(RunEvent(run_id=run.id, ts=int(time.time()), kind='stage', text='failed'))
    run.stage='failed'
    run.error='OUTPUT_INVALID: response failed the project output contract. Process exit evidence is retained; no handoff was accepted.'


def validation_summary(exc):
    from pydantic import ValidationError
    from fastapi import HTTPException
    if isinstance(exc, ValidationError):
        return '\n'.join('.'.join(str(v) for v in e['loc']) + ': ' + e['msg'] for e in exc.errors(include_input=False)[:8])[:1800]
    if isinstance(exc, HTTPException) and isinstance(exc.detail, str):
        return exc.detail[:1800]
    return 'Return one JSON object with the requested fields, field types and story boundaries.'
