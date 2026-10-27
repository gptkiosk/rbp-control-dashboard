"""Route policy: which providers, runtimes, models and cost classes may be used, app-wide or for one project.

A policy only removes routes. Three scopes stack and each can only narrow the one above it: an optional managed policy set at install time
(MAC_CONTROL_MANAGED_ROUTE_POLICY, a file on the host), the app policy (saved with the billing configuration) and a project's policy (saved in its
document). Each scope may narrow one feature further. Nothing here grants access, approves spending or starts a run.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

RUNTIMES = ('claude', 'codex', 'grok', 'hermes', 'openclaw')
FEATURES = ('coordinator', 'planner', 'stories', 'chat', 'tasks')
# Native CLIs reach one provider each. Hermes and OpenClaw name the provider in the model id.
NATIVE_PROVIDER = {'claude': 'anthropic', 'codex': 'openai', 'grok': 'xai'}
PREFIX_PROVIDER = {'x-ai': 'xai', 'xai': 'xai', 'anthropic': 'anthropic', 'openai': 'openai', 'google': 'google', 'meta-llama': 'meta',
                   'mistralai': 'mistral', 'deepseek': 'deepseek', 'qwen': 'qwen', 'moonshotai': 'moonshot', 'z-ai': 'zhipu'}
# Routes whose provider is chosen per request: hidden under any provider filter.
ROUTER = 'router'
ROUTER_ALIASES = {'openrouter/free', 'openrouter/auto', 'free', 'auto'}
COST_CLASSES = ('free', 'subscription', 'paid')
# Preference among allowed routes: memberships first, then free, and paid API (or an unreviewed price) only as a last resort, because it bills
# per token on top of any membership (for example Grok Build membership before xAI models through OpenRouter).
COST_RANK = {'subscription': 0, 'free': 1, 'paid': 2, None: 3}


def cost_rank(cost_class):
    return COST_RANK.get(cost_class if cost_class in COST_CLASSES else None, 3)


# The project task roles of the planning pipeline and the feature that governs each.
COORDINATOR_ROLES = {'coordinate', 'dispatch'}

Runtime = Literal['claude', 'codex', 'grok', 'hermes', 'openclaw']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Models(Strict):
    allow: list[str] = Field(default_factory=list, max_length=100)
    block: list[str] = Field(default_factory=list, max_length=100)


class Cost(Strict):
    free: bool = True
    membership: bool = True
    paid: bool = False


class Filter(Strict):
    """One scope's limits. None and empty lists mean no restriction."""
    providers: list[str] | None = Field(default=None, max_length=30)
    runtimes: list[Runtime] | None = None
    models: Models = Field(default_factory=Models)
    cost: Cost = Field(default_factory=Cost)
    # Specific free models (never router aliases) from any provider, offered as free options under a provider filter.
    any_free: bool = False


class Choice(Strict):
    runtime: Runtime
    model: str = Field(min_length=1, max_length=120)


class Policy(Filter):
    # A feature's own rule in this scope, used instead of the scope's base filter for that feature.
    features: dict[Literal['coordinator', 'planner', 'stories', 'chat', 'tasks'], Filter] = Field(default_factory=dict)
    defaults: dict[Literal['coordinator', 'planner', 'stories', 'chat', 'tasks'], Choice] = Field(default_factory=dict)


class PolicyError(ValueError):
    pass


def provider_of(runtime, model):
    """Who makes the model: 'anthropic', 'openai', 'xai', ..., or 'router' when the provider is picked per request."""
    model = (model or '').strip()
    if runtime in NATIVE_PROVIDER:
        return NATIVE_PROVIDER[runtime]
    bare = model.removeprefix('openrouter/')
    if bare in ROUTER_ALIASES or not bare:
        return ROUTER
    prefix = bare.split('/', 1)[0].lower() if '/' in bare else ''
    if not prefix:
        return _bare_provider(bare)
    return PREFIX_PROVIDER.get(prefix, prefix)


def _bare_provider(model):
    """A model id without a vendor prefix, as some Hermes providers take it."""
    m = model.lower()
    for start, provider in (('claude', 'anthropic'), ('gpt', 'openai'), ('o3', 'openai'), ('o4', 'openai'), ('grok', 'xai'), ('gemini', 'google'), ('gemma', 'google')):
        if m.startswith(start):
            return provider
    return ROUTER


def _cost_name(cost_class):
    return {'free': 'free', 'subscription': 'membership', 'paid': 'paid'}.get(cost_class)


def check(route, f: Filter, scope, unknown_ok=False):
    """Why one scope removes this route, or None. route: runtime, model, provider, cost_class."""
    label = {'managed': 'Managed by this installation', 'app': 'App policy', 'project': 'Project policy'}[scope]
    if f.runtimes is not None and route['runtime'] not in f.runtimes:
        return f'{label}: {route["runtime"]} is not allowed'
    model = route['model']
    if model in f.models.block:
        return f'{label}: this model is blocked'
    if f.models.allow and model not in f.models.allow:
        return f'{label}: not in the allowed models'
    free_extra = f.any_free and route['cost_class'] == 'free' and route['provider'] != ROUTER
    if f.providers is not None and route['provider'] not in f.providers and not free_extra:
        if route['provider'] == ROUTER:
            return f'{label}: provider varies per request'
        return f'{label}: {route["provider"]} is not an allowed provider'
    # A route whose price was never reviewed may cost money, so it counts as paid API when a run is admitted (as the dispatch gate already
    # treats it). Planning and plan checks pass `unknown_ok`: there an unreviewed price is a warning, and admission decides.
    if route['cost_class'] is None and unknown_ok:
        return None
    name = _cost_name(route['cost_class']) or 'paid'
    if not getattr(f.cost, name):
        unreviewed = ' (price not reviewed, so it counts as paid)' if route['cost_class'] is None else ''
        return f'{label}: ' + {'free': 'free models are off', 'membership': 'membership routes are off', 'paid': 'paid API is off'}[name] + unreviewed
    return None


def layers(managed, app, project, feature):
    """(scope, filter) pairs in order, outermost first. Missing scopes are skipped. Within one scope a feature's own filter is that scope's rule
    for the feature (so an install can allow paid API for the Coordinator only); across scopes every filter applies, so a scope only narrows."""
    out = []
    for scope, policy in (('managed', managed), ('app', app), ('project', project)):
        if policy is None:
            continue
        out.append((scope, policy.features.get(feature) or policy))
    return out


def reason(route, managed, app, project, feature, coordinator=None, unknown_ok=False):
    """The first reason a route is not allowed for this feature, or None when every scope allows it. `coordinator` is the runtime that holds
    the Coordinator role (Settings → Agent roles, Hermes by default); only it can run Coordinator work."""
    if feature == 'coordinator' and coordinator and route['runtime'] != coordinator:
        return f'The Coordinator is {coordinator} (Settings → Agent roles)'
    for scope, f in layers(managed, app, project, feature):
        why = check(route, f, scope, unknown_ok)
        if why:
            return why
    return None


def runtimes_allowed(policy):
    """Runtimes a policy allows for at least one feature, or None when there is no policy. Claude, Codex and Grok reach one provider each, so a
    provider list that leaves theirs out, or cost classes without membership or paid API, removes them too. Agent tools, Setup and Billing &
    rates hide the others under an installation-managed policy."""
    if policy is None:
        return None
    out = []
    for runtime in RUNTIMES:
        for f in (policy, *policy.features.values()):
            if f.runtimes is not None and runtime not in f.runtimes:
                continue
            native = NATIVE_PROVIDER.get(runtime)
            if native and ((f.providers is not None and native not in f.providers) or not (f.cost.membership or f.cost.paid)):
                continue
            if not native and not (f.cost.free or f.cost.membership or f.cost.paid):
                continue
            out.append(runtime)
            break
    return out


# --------------------------------------------------------------------------- storage

def default_app(s, settings):
    """The first app policy, written once at startup when none is saved (ensure_saved). It keeps what this host already allowed:
    memberships stay on unless the operator had switched them off under free-only, and paid API stays as the retired free-only setting left it
    (off on RCD, which defaulted to free-only; on with per-plan approval on MCD). After this the old setting and switches are never read."""
    from models import BillingConfig
    row = s.get(BillingConfig, 1)
    saved = ((json.loads(row.payload) if row else {}).get('limits') or {})
    free_only = bool(getattr(settings, 'dispatch_free_only', True))
    return Policy(cost=Cost(free=True,
                            membership=not free_only or saved.get('allow_subscription_in_free_only', True) is not False,
                            paid=not free_only or saved.get('allow_paid_in_free_only', False) is True))


def ensure_saved(s, settings):
    """Persist the first app policy so later reads never fall back to the retired free-only setting. Returns True when it wrote one."""
    _, saved = load_app(s, settings)
    if saved:
        return False
    save_app(s, default_app(s, settings))
    return True


def load_app(s, settings):
    from models import BillingConfig
    row = s.get(BillingConfig, 1)
    saved = (json.loads(row.payload) if row else {}).get('route_policy')
    if saved is None:
        return default_app(s, settings), False
    try:
        return Policy.model_validate(saved), True
    except ValidationError:
        # A damaged saved policy never widens access: fall back to the stricter of the derived default and nothing paid.
        return default_app(s, settings).model_copy(update={'cost': Cost(free=True, membership=False, paid=False)}), True


def save_app(s, policy: Policy):
    from models import BillingConfig
    # The retired free-only switches are dropped with the first save, so nothing can read them again.
    row = s.get(BillingConfig, 1)
    old = json.loads(row.payload) if row else {}
    old['route_policy'] = policy.model_dump(mode='json')
    for key in ('allow_subscription_in_free_only', 'allow_paid_in_free_only'):
        (old.get('limits') or {}).pop(key, None)
    if row:
        row.payload = json.dumps(old)
    else:
        s.add(BillingConfig(id=1, payload=json.dumps(old)))
    s.flush()
    return policy


def load_managed(settings):
    """(policy, error). A managed file that is set but unreadable or invalid locks everything (fails closed)."""
    path = getattr(settings, 'managed_route_policy', None)
    if not path:
        return None, None
    try:
        p = Path(path)
        if p.stat().st_size > 64_000:
            raise PolicyError('too large')
        return Policy.model_validate(json.loads(p.read_text())), None
    except (OSError, ValueError, PolicyError, ValidationError):
        return Policy(runtimes=[], cost=Cost(free=False, membership=False, paid=False)), 'The managed route policy file is missing or invalid, so no route is allowed. Fix the file named by MAC_CONTROL_MANAGED_ROUTE_POLICY.'


def load_project(document):
    """A project's policy, or None for "Same as app"."""
    raw = (document or {}).get('route_policy')
    if raw is None:
        return None
    try:
        return Policy.model_validate(raw)
    except ValidationError:
        return Policy(runtimes=[])  # Invalid saved data never widens: this project allows nothing until it is saved again.


def review_price(s, settings, runtime, target, model, cost_class):
    """Record the price class the operator reviewed for one route (Models & providers → Prices to review), or clear it with None.
    "paid" can be recorded for any route. "free" only for Hermes or OpenClaw and a model that is a free variant or listed at no cost in the
    cached OpenRouter list, so a review can never turn a billed route into a free one. A membership comes from Billing & rates, not here."""
    import billing
    import route_catalog
    if runtime not in RUNTIMES or not model or len(model) > 200 or len(target or '') > 200:
        raise PolicyError('Unknown route.')
    if cost_class not in (None, *billing.REVIEWABLE_CLASSES):
        raise PolicyError('A price can be reviewed as free or paid API. Memberships are set in Billing & rates.')
    if cost_class == 'free':
        listed = route_catalog._listed(settings).get(model.removeprefix('openrouter/')) or {}
        if runtime not in ('hermes', 'openclaw') or not (billing.is_free(model) or listed.get('free') is True):
            raise PolicyError('Only a free model variant, or one the OpenRouter list shows at no cost, can be marked free.')
    billing.save_route_price(s, f'{runtime}|{target or ""}|{model}', cost_class)


# --------------------------------------------------------------------------- enforcement

def route_of(s, settings, runtime, model, target=''):
    """One route as the policy sees it: provider and reviewed cost class (None when the price was never reviewed)."""
    from types import SimpleNamespace
    from dispatch_gate import reviewed_route_class
    model = model or _default_model(settings, runtime)
    cost_class = reviewed_route_class(s, settings, SimpleNamespace(agent=runtime, agent_target=target or ''), model)
    return {'runtime': runtime, 'model': model, 'target': target or '', 'provider': provider_of(runtime, model),
            'cost_class': cost_class if cost_class in COST_CLASSES else None}


def _default_model(settings, runtime):
    from agents import REGISTRY
    if runtime in {'hermes', 'openclaw'}:
        import native_routes
        return native_routes.read(settings).get(runtime, {}).get('default') or ''
    spec = REGISTRY.get(runtime)
    return (spec.default_model() or (spec.suggested_models[0] if spec.suggested_models else '')) if spec else ''


def coordinator_runtime(settings):
    try:
        from role_pack import RoleStore
        return RoleStore(settings).delegator()
    except Exception:  # noqa: BLE001 - an unreadable role store leaves the Coordinator unassigned, which planning already refuses
        return None


def allowed(s, settings, runtime, model, feature, project=None, target='', unknown_ok=False):
    """Why this route may not be used for the feature (and project), or None when it may."""
    import projects
    managed, error = load_managed(settings)
    app, _ = load_app(s, settings)
    project_policy = load_project(projects.document(project)) if project is not None else None
    if error:
        return error
    return reason(route_of(s, settings, runtime, model, target), managed, app, project_policy, feature,
                  coordinator_runtime(settings) if feature == 'coordinator' else None, unknown_ok)


def cost_allowed(s, settings, cost_class):
    """Whether the installation and app policies allow a cost class at all (any feature). An unreviewed price counts as paid."""
    managed, error = load_managed(settings)
    if error:
        return False
    app, _ = load_app(s, settings)
    name = _cost_name(cost_class) or 'paid'
    return all(getattr(p.cost, name) or any(getattr(f.cost, name) for f in p.features.values()) for p in (managed, app) if p is not None)


def feature_of(s, source):
    """(feature, project) for a board card or chat thread about to run."""
    from models import ChatThread, Project
    import projects
    if isinstance(source, ChatThread):
        return 'chat', None
    link = projects.binding(s, source.id) if getattr(source, 'id', None) else None
    if not link:
        return 'tasks', None
    project = s.get(Project, link.project_id)
    if link.role == 'story':
        return 'stories', project
    if link.role in COORDINATOR_ROLES or (link.role == 'return plan' and source.agent == coordinator_runtime_for(project)):
        return 'coordinator', project
    return 'planner', project


def coordinator_runtime_for(project):
    pipeline = json.loads(project.pipeline or '{}') if project is not None else {}
    return (pipeline.get('delegator') or {}).get('agent')


def run_reason(s, settings, source, model):
    """Why a claimed run may not start under the current route policy, or None."""
    feature, project = feature_of(s, source)
    return allowed(s, settings, source.agent, model, feature, project, getattr(source, 'agent_target', None) or '')


def story_findings(s, settings, document, project=None):
    """Plan-check findings for story routes the project's policy does not allow. A primary route outside policy blocks submission; a backup
    outside policy is only a warning, because the dispatch gate refuses it when it is reached."""
    managed, error = load_managed(settings)
    app, _ = load_app(s, settings)
    project_policy = load_project(document)
    blocked, backups, unreviewed = {}, {}, []
    for n in document.get('nodes', ()):
        if n.get('kind', 'story') != 'story' or n.get('assignee') in (None, 'human'):
            continue
        primary = route_of(s, settings, n['assignee'], n.get('model', ''), n.get('agent_target', ''))
        why = error or reason(primary, managed, app, project_policy, 'stories', unknown_ok=True)
        if why:
            blocked.setdefault(why, []).append(n['key'])
        elif reason(primary, managed, app, project_policy, 'stories'):
            unreviewed.append(n['key'])
        for r in n.get('routes', ()):
            if error or reason(route_of(s, settings, r['agent'], r['model']), managed, app, project_policy, 'stories', unknown_ok=True):
                backups.setdefault(n['key'], []).append(f"{r['agent']} · {r['model']}")
    out = []
    for why, keys in blocked.items():
        out.append({'id': 'route-policy', 'severity': 'block', 'stories': keys,
                    'message': f'{len(keys)} stor{"y uses a route" if len(keys) == 1 else "ies use routes"} the route policy does not allow ({why}). '
                               'Choose an allowed route for them, or use Route all stories… with the policy\'s story default.'})
    if unreviewed:
        out.append({'id': 'route-policy-unreviewed', 'severity': 'warn', 'stories': unreviewed,
                    'message': 'These stories use a route whose price was never reviewed. It counts as paid API when it starts, so it will be refused '
                               'while paid API is off. Review its billing class in Agents → Billing & rates or choose another route.'})
    if backups:
        out.append({'id': 'route-policy-backups', 'severity': 'warn', 'stories': list(backups),
                    'message': 'Some backup routes are outside the route policy and will be skipped if reached: '
                               + '; '.join(f'{k}: {", ".join(v)}' for k, v in list(backups.items())[:6])})
    return out
