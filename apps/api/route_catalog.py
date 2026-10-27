"""Every route this host could use, built once from what is installed, and filtered by the route policy for one feature.

Model lists come from each runtime's table in the agent registry (suggested_models, free_models, default_model), the operator's Hermes and
OpenClaw configurations, and the cached OpenRouter list for the providers a policy names. No prompt, credential or provider error is returned.
"""
from types import SimpleNamespace

import route_policy as rp

FEATURE_LABELS = {'coordinator': 'Coordinator', 'planner': 'Planner', 'stories': 'Stories', 'chat': 'Chat', 'tasks': 'Tasks'}
# Free models from the OpenRouter list are many; offer a bounded number.
MAX_LISTED_FREE = 40
MAX_LISTED_PER_PROVIDER = 40


def _listed(settings):
    """id -> {free, prompt_per_m, completion_per_m} from the cached OpenRouter list, or {}."""
    import model_profiles
    snap = model_profiles.snapshot(settings.data_dir) or {}
    return {m['id']: m for m in snap.get('models', []) if isinstance(m, dict) and isinstance(m.get('id'), str)}


def candidates(settings, providers=()):
    """(runtime, target, model) for every route this host could name, in a stable order: memberships, then native configurations."""
    from agents import REGISTRY
    import native_routes
    native = native_routes.read(settings)
    rows = []
    for runtime in ('claude', 'codex', 'grok'):
        spec = REGISTRY[runtime]
        for model in (*spec.suggested_models, spec.default_model() or ''):
            rows.append((runtime, '', model))
    listed = _listed(settings)
    for runtime in ('hermes', 'openclaw'):
        prefix = 'openrouter/' if runtime == 'openclaw' else ''
        config = native.get(runtime, {})
        rows += [(runtime, '', m) for m in (config.get('default') or '', *config.get('models', ()), *REGISTRY[runtime].free_models)]
        rows += [(runtime, t['id'], t.get('model') or '') for t in config.get('targets', ()) if isinstance(t.get('id'), str)]
        free = [m for m, v in listed.items() if v.get('free')][:MAX_LISTED_FREE]
        named = [m for m in listed if rp.provider_of('hermes', m) in providers]
        by_provider = {}
        for m in named:
            by_provider.setdefault(rp.provider_of('hermes', m), []).append(m)
        rows += [(runtime, '', prefix + m) for m in free]
        rows += [(runtime, '', prefix + m) for group in by_provider.values() for m in group[:MAX_LISTED_PER_PROVIDER]]
    seen, out = set(), []
    for row in rows:
        if row[2] and row not in seen:
            seen.add(row)
            out.append(row)
    return out


def catalog(s, settings, providers=()):
    """Each candidate with its provider, reviewed cost class, listed price, readiness and recent reliability."""
    from agents import REGISTRY
    from dispatch_gate import reviewed_route_class
    import route_reliability
    listed = _listed(settings)
    health = {(r['agent'], r['model']): r for r in route_reliability.stats(s)}
    ready = {a: REGISTRY[a].available(settings) for a in rp.RUNTIMES}
    out = []
    for runtime, target, model in candidates(settings, providers):
        cost_class = reviewed_route_class(s, settings, SimpleNamespace(agent=runtime, agent_target=target), model)
        price = listed.get(model.removeprefix('openrouter/')) or {}
        h = health.get((runtime, model)) or {}
        out.append({'runtime': runtime, 'target': target, 'model': model, 'provider': rp.provider_of(runtime, model),
                    'cost_class': cost_class if cost_class in rp.COST_CLASSES else None, 'ready': ready[runtime],
                    'listed_price': {k: price.get(k) for k in ('free', 'prompt_per_m', 'completion_per_m')} if price else None,
                    'reliability': {'attempts': h.get('attempts', 0), 'failures': h.get('failures', 0),
                                    'recent_failures': h.get('recent_failures', 0), 'persistent': bool(h.get('persistent'))}})
    return out


def policies(s, settings, project=None):
    """(managed, managed_error, app, app_saved, project_policy) for one request."""
    managed, error = rp.load_managed(settings)
    app, saved = rp.load_app(s, settings)
    project_policy = rp.load_project(_document(project)) if project is not None else None
    return managed, error, app, saved, project_policy


def _document(project):
    import projects
    return projects.document(project)


def _named_providers(*policies):
    names = set()
    for policy in policies:
        if policy is None:
            continue
        for f in (policy, *policy.features.values()):
            names.update(f.providers or ())
    return names


def _fallback_default(s, settings, feature, project):
    """What the app uses today when no policy default is set: the project's planner fields, Hermes's configured default."""
    if feature == 'planner' and project is not None:
        d = _document(project)
        if d.get('planner_agent') not in (None, 'auto') and d.get('planner_model'):
            return {'runtime': d['planner_agent'], 'model': d['planner_model']}
    if feature == 'coordinator':
        import native_routes
        model = native_routes.read(settings).get('hermes', {}).get('default')
        if model:
            return {'runtime': 'hermes', 'model': model}
    return None


def for_feature(s, settings, feature, project=None):
    """Allowed routes for one feature, the default, and every hidden route with the reason it is hidden."""
    if feature not in rp.FEATURES:
        raise rp.PolicyError('Unknown feature.')
    managed, error, app, saved, project_policy = policies(s, settings, project)
    coordinator = rp.coordinator_runtime(settings) if feature == 'coordinator' else None
    allowed, hidden = [], []
    for route in catalog(s, settings, _named_providers(managed, app, project_policy)):
        # The policy reason first: "not installed" only matters for a route the policy would allow.
        why = error or rp.reason(route, managed, app, project_policy, feature, coordinator) or (
            None if route['ready'] else 'Not installed: install it in Agent tools')
        (hidden if why else allowed).append({**route, **({'hidden_because': why} if why else {})})
    allowed.sort(key=lambda r: rp.cost_rank(r['cost_class']))   # stable: membership, free, then paid API last
    default, default_note = None, None
    for scope_policy in (project_policy, app, managed):
        choice = scope_policy.defaults.get(feature) if scope_policy is not None else None
        if choice:
            default = {'runtime': choice.runtime, 'model': choice.model}
            break
    if default is None:
        default = _fallback_default(s, settings, feature, project)
    keys = {(r['runtime'], r['model']) for r in allowed}
    if default and (default['runtime'], default['model']) not in keys:
        match = next((r for r in hidden if (r['runtime'], r['model']) == (default['runtime'], default['model'])), None)
        default_note = f"The default {default['runtime']} · {default['model']} is not allowed: " + (match['hidden_because'] if match else 'it is not available on this host')
        default = None
    if default is None and allowed:
        default = {'runtime': allowed[0]['runtime'], 'model': allowed[0]['model']}
    return {'feature': feature, 'label': FEATURE_LABELS[feature], 'default': default, 'default_note': default_note,
            'allowed': allowed, 'hidden': hidden,
            'scope': {'managed': managed is not None, 'managed_error': error, 'app_saved': saved,
                      'project': 'narrowed' if project_policy is not None else ('same_as_app' if project is not None else None)},
            'empty_reason': None if allowed else _empty_reason(feature, hidden)}


# Reasons that only say the policy removed a route. Any other reason (not installed, a cost class switched off, an unreviewed price) is the
# actionable one, so the nearest such route is named first.
FILTERED = ('not an allowed provider', 'is not allowed', 'provider varies', 'The Coordinator is', 'not in the allowed models', 'is blocked')


def _empty_reason(feature, hidden):
    """No silent blocks: say why nothing is offered, naming the nearest route and what stops it when there is one."""
    from agents import REGISTRY
    if not hidden:
        return f'No {FEATURE_LABELS[feature]} route is available on this host.'
    near = [r for r in hidden if not any(k in r['hidden_because'] for k in FILTERED)]
    if near:
        r = near[0]
        name = REGISTRY[r['runtime']].name if r['runtime'] in REGISTRY else r['runtime']
        return f"No {FEATURE_LABELS[feature]} route is allowed. Nearest: {name} · {r['model']}: {r['hidden_because']}."
    counts = {}
    for r in hidden:
        counts[r['hidden_because']] = counts.get(r['hidden_because'], 0) + 1
    top = max(counts, key=counts.get)
    return f'No {FEATURE_LABELS[feature]} route is allowed. Most common reason: {top}.'


def policy_view(s, settings):
    """The app and managed policies as the Models & providers page shows them."""
    managed, error, app, saved, _ = policies(s, settings)
    return {'app': app.model_dump(mode='json'), 'app_saved': saved,
            'managed': managed.model_dump(mode='json') if managed is not None else None, 'managed_error': error,
            'features': list(rp.FEATURES), 'runtimes': list(rp.RUNTIMES),
            'providers': sorted({r['provider'] for r in catalog(s, settings, _named_providers(managed, app))} - {rp.ROUTER})}
