"""SEC-013: one fail-closed admission policy for every dispatch route.

Route classes are operator configuration, never billing estimates or agent output.
The launch snapshot is saved at claim time so edits cannot increase a claimed cap.
"""
import json
import math

from agents import SUBSCRIPTION_AGENTS


class DispatchDenied(ValueError):
    pass


def snapshot(source, budget, price_class=None):
    """Freeze the operator-reviewed route class with the launch request.

    ``price_class`` comes from either the exact route registry or the persisted
    account billing mode.  Keeping it in the claim snapshot prevents a later
    settings edit from silently changing an already claimed run.
    """
    return {"target": getattr(source, "agent_target", None) or "",
            "budget_usd": budget, "price_class": price_class}


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


_UNSET = object()


def admit(settings, run, argv, *, current_price_class=_UNSET, limits=None, route_policy_reason=None):
    """Called immediately before spawn/start, for board tasks and chat alike.

    Returns evidence to persist. Spending limits are off unless the operator turned them on (billing.limits): without them a run that can cost money is admitted with
    a disclaimer, and only the checks below that are about correctness (a pinned model, a consistent snapshot) and the route policy still refuse.
    `route_policy_reason` is route_policy.run_reason for this run under the current policy: a policy narrowed after the claim refuses it here.
    """
    limits = {**{"require_reviewed_pricing": False, "per_run_cap_usd": None, "paid_needs_runtime_limit": False}, **(limits or {})}
    try:
        policy = json.loads(run.checkpoint or "{}")["dispatch_policy"]
        if not isinstance(policy, dict):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise DispatchDenied("BUDGET_EXCEEDED: launch policy snapshot missing or invalid") from None
    model = run.model_requested
    if not isinstance(model, str) or not model:
        raise DispatchDenied("PRICE_UNKNOWN: an explicit priced model is required")
    key = f"{run.agent}|{policy.get('target', '')}|{model}"
    price_class = policy.get("price_class")
    if current_price_class is _UNSET:
        current_price_class = getattr(settings, "dispatch_route_classes", {}).get(key)
    if price_class != current_price_class:
        raise DispatchDenied("PRICE_UNKNOWN: reviewed route changed or was revoked after claim")
    reviewed = isinstance(price_class, str) and price_class in {"free", "subscription", "paid"}
    if not reviewed and limits["require_reviewed_pricing"]:
        raise DispatchDenied("PRICE_UNKNOWN: route has no reviewed pricing class")
    if route_policy_reason:
        raise DispatchDenied(f"ROUTE_POLICY: {route_policy_reason}. Change the route or the policy in Models & providers.")
    cap = amount(policy.get("budget_usd"))
    run_cap = amount(limits["per_run_cap_usd"])
    if run_cap and (cap is None or cap > run_cap):     # a per-run cap the operator chose in Spending & limits: the run's budget must be valid and fit under it
        raise DispatchDenied("BUDGET_EXCEEDED: this run's dollar budget is missing, invalid or above the per-run cap you set in Spending & limits")
    # Native default models must never drift after admission. Pi adapters pin the
    # assigned model in their RunSpec instead of argv; their separate scope gate
    # also requires a provider budget boundary.
    flags = {"claude": "--model", "codex": "-m", "grok": "--model", "hermes": "-m", "openclaw": "--model"}
    if run.agent in flags:
        flag = flags[run.agent]
        if argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv) or argv[argv.index(flag) + 1] != model:
            raise DispatchDenied("ROUTE_UNPINNED: command does not pin the admitted model")
    disclaimer = None
    flag = "--max-budget-usd"
    enforced = run.agent == "claude" and argv.count(flag) == 1
    if price_class == "paid" and limits["paid_needs_runtime_limit"]:
        if not cap or cap <= 0:
            raise DispatchDenied("BUDGET_EXCEEDED: paid route requires a positive cap")
        if not enforced:
            raise DispatchDenied("BUDGET_UNENFORCED: runtime has no verified dollar boundary")
    if enforced:
        try:
            runtime_cap = amount(float(argv[argv.index(flag) + 1]))
        except (ValueError, IndexError):
            runtime_cap = None
        if cap and (runtime_cap is None or runtime_cap <= 0 or runtime_cap > cap):
            raise DispatchDenied("BUDGET_UNENFORCED: runtime cap exceeds admitted budget")
    if price_class == "paid" and not (enforced and cap):
        disclaimer = ("This route is paid and MCD does not limit its spending: it bills your provider account or key. "
                      "Set a credit limit with your provider (for OpenRouter, on the key). MCD limits are off unless you turn them on in Agents, Billing & rates, Spending & limits.")
    elif not reviewed:
        disclaimer = ("This route's price has not been reviewed, so it may cost money. MCD does not limit spending unless you turn a limit on in Agents, Billing & rates, Spending & limits.")
    return {"route": key, "price_class": price_class, "budget_usd": cap,
            "route_policy": "allowed", **({"disclaimer": disclaimer} if disclaimer else {})}


def reviewed_route_class(s, settings, source, model: str | None) -> str | None:
    """Resolve a route from operator-owned configuration at claim time.

    Exact route entries take precedence. Claude and Codex may also use the
    effective subscription account mode. An approved project revision may
    classify its exact pinned OpenClaw ``:free`` route; no agent output or
    unreviewed model-name guess can classify an API route as free or paid.
    """
    import projects
    import billing
    from models import Card

    agent = source.agent
    target = getattr(source, "agent_target", None)
    key = f"{agent}|{target or ''}|{model or ''}"
    configured = getattr(settings, "dispatch_route_classes", {}).get(key)
    if key in getattr(settings, "dispatch_route_classes", {}):
        return configured
    # A price the operator reviewed in Models & providers (billing.route_prices). The installation's configured classes above win.
    try:
        reviewed = billing.route_prices(s).get(key)
    except (ValueError, TypeError, AttributeError):
        reviewed = None
    if reviewed:
        return reviewed
    # The exact configured Hermes free route is operator-owned evidence.
    # Capped Google BYOK is still API billing and must never be classified free.
    if agent == "hermes" and model:
        from native_routes import read
        native = read(settings).get("hermes", {})
        if model in native.get("models", ()) and (model.endswith(":free") or model in {"openrouter/free", "openrouter/openrouter/free"}):
            return "free"
    try:
        # Use the same effective account configuration shown by Billing & rates
        # and used by project planning. An unchanged dialog save must not be a
        # hidden prerequisite for dispatch.
        account = billing.config(s)["accounts"].get(agent, {})
        if agent in SUBSCRIPTION_AGENTS and account.get("mode") == "subscription":
            return "subscription"
    except (ValueError, TypeError, AttributeError):
        return None
    # Project submission is an operator review of the immutable story route.
    # Admit only the story's exact primary OpenClaw model and target, and only
    # when the pinned route itself declares the provider's free tier.
    source_id = getattr(source, "id", None)
    link = projects.binding(s, source_id) if source_id else None
    if isinstance(source, Card) and link and agent == "openclaw":
        manifest = json.loads(projects.get(s, link.project_id).approved_manifest or "{}")
        node = next((row for row in manifest.get("document", {}).get("nodes", ())
                     if row.get("key") == link.node_key), None)
        if (node and node.get("assignee") == agent and node.get("model") == model
                and (node.get("agent_target") or "") == (target or "")
                and (model.endswith(":free") or model in {"openrouter/free", "openrouter/openrouter/free"})):
            return "free"
        # Go Free is a separate operator action recorded as an exact route and
        # target in the same immutable manifest. No other API route inherits it.
        approved = manifest.get("free_retries", {}).get(link.node_key, {})
        if (approved.get("route") == {"agent": agent, "model": model}
                and approved.get("agent_target") == (target or "")):
            return "free"
        approved_paid = manifest.get("paid_retries", {}).get(link.node_key, {})
        if (approved_paid.get("route") == {"agent": agent, "model": model}
                and approved_paid.get("agent_target") == (target or "")):
            return "paid"
    return None


FREE_ALIASES = {"openrouter/free", "openrouter/openrouter/free"}


def resolve_free_alias(s, settings, agent, agent_target, model):
    """The model a new task or chat will really use.

    "openrouter/free" is the dashboard's generic default, not a model Hermes or OpenClaw list in their own config, so the gate has no reviewed
    pricing for it and refuses the run (PRICE_UNKNOWN). The alias is replaced by the free model the agent is set up with (its default, or the
    default of the chosen OpenClaw target), and only when that exact route is reviewed as free. A model chosen by name is never replaced and a
    paid default is never chosen for the operator."""
    from types import SimpleNamespace
    if agent not in ("hermes", "openclaw") or (model and model not in FREE_ALIASES):
        return model
    def route(m):
        return reviewed_route_class(s, settings, SimpleNamespace(agent=agent, agent_target=agent_target, id=None), m)
    if model and route(model) == "free":
        return model
    from native_routes import read
    native = read(settings).get(agent, {})
    target = next((t for t in native.get("targets", ()) if t.get("id") == agent_target), None) if agent_target else None
    default = (target or {}).get("model") or native.get("default")
    return default if default and route(default) == "free" else model
