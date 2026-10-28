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
# When a policy allows paid API with every provider open, the paid models of these common providers are listed too (fewer each), so a paid
# Coordinator or story model can be chosen without first limiting providers.
COMMON_PROVIDERS = ('anthropic', 'openai', 'xai', 'google', 'meta', 'mistral', 'deepseek', 'qwen')
MAX_LISTED_OPEN = 12


def _listed(settings):
    """id -> {free, prompt_per_m, completion_per_m} from the cached OpenRouter list, or {}."""
    import model_profiles
    snap = model_profiles.snapshot(settings.data_dir) or {}
    return {m['id']: m for m in snap.get('models', []) if isinstance(m, dict) and isinstance(m.get('id'), str)}


def candidates(settings, providers=()):
    """(runtime, target, model) for every route this host could name, in a stable order: memberships, then native configurations.
    `providers` names the providers whose listed models to add: a list (up to MAX_LISTED_PER_PROVIDER each) or {provider: cap}."""
    caps = providers if isinstance(providers, dict) else {name: MAX_LISTED_PER_PROVIDER for name in providers}
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
        named = [m for m in listed if rp.provider_of('hermes', m) in caps]
        by_provider = {}
        for m in named:
            by_provider.setdefault(rp.provider_of('hermes', m), []).append(m)
        rows += [(runtime, '', prefix + m) for m in free]
        rows += [(runtime, '', prefix + m) for name, group in by_provider.items() for m in group[:caps[name]]]
    seen, out = set(), []
    for row in rows:
        if row[2] and row not in seen:
            seen.add(row)
            out.append(row)
    return out


def catalog(s, settings, providers=()):
    """Each candidate with its provider, reviewed cost class, listed price, readiness and recent reliability. Built once per request (session)
    for the same providers and billing settings: a preview or the AI & models page asks for several features at once."""
    from models import BillingConfig
    row = s.get(BillingConfig, 1)
    key = (tuple(sorted(providers.items())) if isinstance(providers, dict) else tuple(sorted(providers)), row.payload if row else None)
    memo = s.info.setdefault('route_catalog', {})
    hit = memo.get(key[0])
    if hit is not None and hit[0] is key[1]:
        return [dict(r) for r in hit[1]]
    rows = _catalog(s, settings, providers)
    memo[key[0]] = (key[1], rows)
    return [dict(r) for r in rows]


def _catalog(s, settings, providers=()):
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


_SAVED = object()


def policies(s, settings, project=None, draft=_SAVED):
    """(managed, managed_error, app, app_saved, project_policy) for one request. `draft` replaces the project's saved policy (None: Same as
    app) to preview unsaved choices."""
    managed, error = rp.load_managed(settings)
    app, saved = rp.load_app(s, settings)
    if draft is not _SAVED:
        return managed, error, app, saved, draft
    project_policy = rp.load_project(_document(project)) if project is not None else None
    return managed, error, app, saved, project_policy


def _document(project):
    import projects
    return projects.document(project)


def _named_providers(*policies):
    """{provider: cap} for the listed models to add: every provider a policy names, and the common providers (fewer each) when a rule allows
    paid API with every provider open."""
    names = {}
    for policy in policies:
        if policy is None:
            continue
        for f in (policy, *policy.features.values()):
            for name in f.providers or ():
                names[name] = MAX_LISTED_PER_PROVIDER
            if f.providers is None and f.cost.paid:
                for name in COMMON_PROVIDERS:
                    names.setdefault(name, MAX_LISTED_OPEN)
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


def for_feature(s, settings, feature, project=None, draft=_SAVED):
    """Allowed routes for one feature, the default, and every hidden route with the reason it is hidden. `draft` previews an unsaved
    project policy (policies())."""
    if feature not in rp.FEATURES:
        raise rp.PolicyError('Unknown feature.')
    managed, error, app, saved, project_policy = policies(s, settings, project, draft)
    coordinator = rp.coordinator_runtime(settings) if feature == 'coordinator' else None
    allowed, hidden = [], []
    for route in catalog(s, settings, _named_providers(managed, app, project_policy)):
        # The policy reason first: "not installed" only matters for a route the policy would allow.
        why = error or rp.reason(route, managed, app, project_policy, feature, coordinator) or (
            None if route['ready'] else 'Not installed: install it in Agent tools')
        (hidden if why else allowed).append({**route, **({'hidden_because': why} if why else {})})
    allowed.sort(key=lambda r: rp.cost_rank(r['cost_class']))   # stable: membership, free, then paid API last
    default, default_note, source = None, None, None
    for name, scope_policy in (('project', project_policy), ('app', app), ('managed', managed)):
        choice = scope_policy.defaults.get(feature) if scope_policy is not None else None
        if choice:
            default, source = {'runtime': choice.runtime, 'model': choice.model}, name
            break
    if default is None:
        default = _fallback_default(s, settings, feature, project)
        source = 'configured' if default else None
    keys = {(r['runtime'], r['model']) for r in allowed}
    if default and (default['runtime'], default['model']) not in keys:
        match = next((r for r in hidden if (r['runtime'], r['model']) == (default['runtime'], default['model'])), None)
        default_note = f"The default {default['runtime']} · {default['model']} is not allowed: " + (match['hidden_because'] if match else 'it is not available on this host')
        default = None
    if default is None and allowed:
        default, source = {'runtime': allowed[0]['runtime'], 'model': allowed[0]['model']}, 'first_allowed'
    # default_source: where the default came from: a policy's Defaults ('project', 'app', 'managed'), the project's or runtime's own setting
    # ('configured'), or the first allowed route ('first_allowed').
    return {'feature': feature, 'label': FEATURE_LABELS[feature], 'default': default, 'default_note': default_note,
            'default_source': source if default else None,
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


def prices(s, settings):
    """Prices to review: routes the policy would allow except that their price was never reviewed (so they count as paid API), and the
    reviews the operator already recorded here."""
    import billing
    managed, error, app, _, _ = policies(s, settings)
    reviewed = billing.route_prices(s)
    rows = catalog(s, settings, _named_providers(managed, app))
    def relevant(route):
        return not error and any(rp.reason(route, managed, app, None, f, None, unknown_ok=True) is None for f in rp.FEATURES)
    def can_free(route):
        return route['runtime'] in ('hermes', 'openclaw') and (billing.is_free(route['model']) or bool((route['listed_price'] or {}).get('free')))
    pending = [{**r, 'can_mark_free': can_free(r)} for r in rows if r['cost_class'] is None and relevant(r)]
    pending.sort(key=lambda r: (not r['can_mark_free'], r['runtime'], r['model']))
    done = []
    for key, cost_class in sorted(reviewed.items()):
        runtime, target, model = (key.split('|', 2) + ['', ''])[:3]
        done.append({'runtime': runtime, 'target': target, 'model': model, 'cost_class': cost_class})
    return {'pending': pending, 'reviewed': done}


def policy_view(s, settings):
    """The app and managed policies as the AI & models page shows them."""
    managed, error, app, saved, _ = policies(s, settings)
    return {'app': app.model_dump(mode='json'), 'app_saved': saved,
            'managed': managed.model_dump(mode='json') if managed is not None else None, 'managed_error': error,
            'managed_runtimes': rp.runtimes_allowed(managed),
            'features': list(rp.FEATURES), 'runtimes': list(rp.RUNTIMES),
            'providers': sorted({r['provider'] for r in catalog(s, settings, _named_providers(managed, app))} - {rp.ROUTER})}
