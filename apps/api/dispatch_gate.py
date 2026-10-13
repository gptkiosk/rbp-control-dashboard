"""SEC-013: one fail-closed admission policy for every dispatch route.

Route classes are operator configuration, never billing estimates or agent output.
The launch snapshot is saved at claim time so edits cannot increase a claimed cap.
"""
import json
import math


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


def admit(settings, run, argv, *, default_free_only=True, current_price_class=_UNSET):
    """Called immediately before spawn/start, for board tasks and chat alike.

    Returns evidence to persist. A paid route needs a runtime dollar boundary;
    currently only the Claude CLI provides one among the four legacy adapters.
    """
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
    if not isinstance(price_class, str) or price_class not in {"free", "subscription", "paid"}:
        raise DispatchDenied("PRICE_UNKNOWN: route has no reviewed pricing class")
    if getattr(settings, "dispatch_free_only", default_free_only) and price_class != "free":
        raise DispatchDenied("FREE_ONLY: only reviewed free routes may start")
    cap = amount(policy.get("budget_usd"))
    host_cap = amount(getattr(settings, "dispatch_max_budget_usd", 1.0))
    if cap is None or host_cap is None or cap > host_cap:
        raise DispatchDenied("BUDGET_EXCEEDED: missing, invalid or above host run cap")
    # Native default models must never drift after admission. Pi adapters pin the
    # assigned model in their RunSpec instead of argv; their separate scope gate
    # also requires a provider budget boundary.
    flags = {"claude": "--model", "codex": "-m", "hermes": "-m", "openclaw": "--model"}
    if run.agent in flags:
        flag = flags[run.agent]
        if argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv) or argv[argv.index(flag) + 1] != model:
            raise DispatchDenied("ROUTE_UNPINNED: command does not pin the admitted model")
    if price_class == "paid":
        if cap <= 0:
            raise DispatchDenied("BUDGET_EXCEEDED: paid route requires a positive cap")
        flag = "--max-budget-usd"
        if run.agent != "claude" or argv.count(flag) != 1:
            raise DispatchDenied("BUDGET_UNENFORCED: runtime has no verified dollar boundary")
        try:
            runtime_cap = amount(float(argv[argv.index(flag) + 1]))
        except (ValueError, IndexError):
            runtime_cap = None
        if runtime_cap is None or runtime_cap <= 0 or runtime_cap > cap:
            raise DispatchDenied("BUDGET_UNENFORCED: runtime cap exceeds admitted budget")
    return {"route": key, "price_class": price_class, "budget_usd": cap,
            "free_only": getattr(settings, "dispatch_free_only", default_free_only)}


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
    try:
        # Use the same effective account configuration shown by Billing & rates
        # and used by project planning. An unchanged dialog save must not be a
        # hidden prerequisite for dispatch.
        account = billing.config(s)["accounts"].get(agent, {})
        if agent in {"claude", "codex"} and account.get("mode") == "subscription":
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
                and model.endswith(":free")):
            return "free"
        # Go Free is a separate operator action recorded as an exact route and
        # target in the same immutable manifest. No other API route inherits it.
        approved = manifest.get("free_retries", {}).get(link.node_key, {})
        if (approved.get("route") == {"agent": agent, "model": model}
                and approved.get("agent_target") == (target or "")):
            return "free"
    return None
