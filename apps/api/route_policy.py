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
# v1: only Hermes holds the Coordinator role. The policy chooses its model.
FEATURE_RUNTIMES = {'coordinator': ('hermes',)}
# Native CLIs reach one provider each. Hermes and OpenClaw name the provider in the model id.
NATIVE_PROVIDER = {'claude': 'anthropic', 'codex': 'openai', 'grok': 'xai'}
PREFIX_PROVIDER = {'x-ai': 'xai', 'xai': 'xai', 'anthropic': 'anthropic', 'openai': 'openai', 'google': 'google', 'meta-llama': 'meta',
                   'mistralai': 'mistral', 'deepseek': 'deepseek', 'qwen': 'qwen', 'moonshotai': 'moonshot', 'z-ai': 'zhipu'}
# Routes whose provider is chosen per request: hidden under any provider filter.
ROUTER = 'router'
ROUTER_ALIASES = {'openrouter/free', 'openrouter/auto', 'free', 'auto'}
COST_CLASSES = ('free', 'subscription', 'paid')

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


def check(route, f: Filter, scope):
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
    name = _cost_name(route['cost_class'])
    if name is None:
        return 'Price not reviewed: set its billing class in Agents → Billing & rates'
    if not getattr(f.cost, name):
        return f'{label}: ' + {'free': 'free models are off', 'membership': 'membership routes are off', 'paid': 'paid API is off'}[name]
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


def reason(route, managed, app, project, feature):
    """The first reason a route is not allowed for this feature, or None when every scope allows it."""
    only = FEATURE_RUNTIMES.get(feature)
    if only and route['runtime'] not in only:
        return 'Only Hermes coordinates in this version'
    for scope, f in layers(managed, app, project, feature):
        why = check(route, f, scope)
        if why:
            return why
    return None


# --------------------------------------------------------------------------- storage

def default_app(s, settings):
    """The app policy before the operator saves one: the cost classes today's settings already allow, every provider and runtime."""
    import billing
    limits = billing.limits(s, settings)
    free_only = getattr(settings, 'dispatch_free_only', True)
    return Policy(cost=Cost(free=True, membership=not free_only or limits.get('allow_subscription_in_free_only', False),
                            paid=not free_only or limits.get('allow_paid_in_free_only', False)))


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
    row = s.get(BillingConfig, 1)
    old = json.loads(row.payload) if row else {}
    old['route_policy'] = policy.model_dump(mode='json')
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
