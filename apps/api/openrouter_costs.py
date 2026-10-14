"""Read-only OpenRouter key spending. Credentials never enter payloads, logs or storage."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ENDPOINT = "https://openrouter.ai/api/v1/key"
FIELDS = {
    "today_usd": "usage_daily",
    "week_usd": "usage_weekly",
    "month_usd": "usage_monthly",
    "lifetime_usd": "usage",
    "byok_today_usd": "byok_usage_daily",
    "byok_week_usd": "byok_usage_weekly",
    "byok_month_usd": "byok_usage_monthly",
    "byok_lifetime_usd": "byok_usage",
    "limit_usd": "limit",
    "remaining_usd": "limit_remaining",
}


def amount(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def env_file(path):
    # No interpolation: never substitute unrelated environment credentials.
    return dotenv_values(path, interpolate=False) if path.is_file() else {}


def configured_keys(home, saved=None):
    """Default provider keys only. An explicit MCD override can match injected credentials."""
    home = Path(home)
    overrides = env_file(home / ".mac-control/.env")
    keys = {}
    for agent, folder in (("hermes", ".hermes"), ("openclaw", ".openclaw")):
        override = overrides.get(f"MAC_CONTROL_OPENROUTER_{agent.upper()}_KEY")
        local = env_file(home / folder / ".env")
        key = override or local.get("OPENROUTER_API_KEY")
        if agent == "openclaw" and not override:
            config = home / folder / "openclaw.json"
            if config.is_file():
                provider = json.loads(config.read_text()).get("models", {}).get("providers", {}).get("openrouter", {})
                value = provider.get("apiKey")
                if isinstance(value, str):
                    if value in ("${OPENROUTER_API_KEY}", "$OPENROUTER_API_KEY", "OPENROUTER_API_KEY", "env:OPENROUTER_API_KEY"):
                        key = local.get("OPENROUTER_API_KEY")
                    else:
                        key = value
                elif value:
                    # Secret references must be resolved by the operator through the override.
                    key = None
        # Accept only a literal credential; unresolved refs never become Authorization headers.
        keys[agent] = key.strip() if isinstance(key, str) and key.strip().startswith("sk-or-") else None
        if isinstance(saved, str) and saved.startswith("sk-or-"):
            keys[agent] = saved   # the operator chose to share the saved key: it is what these agents run with
    return keys


def fetch_key(key):
    with httpx.Client(timeout=6, follow_redirects=False, trust_env=False) as client:
        response = client.get(ENDPOINT, headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        data = response.json().get("data")
        if not isinstance(data, dict) or amount(data.get("usage")) is None:
            raise ValueError("Missing spending data")
        # Allowlist only numerical amounts; never return provider labels/key fragments or errors.
        return {**{name: amount(data.get(field)) for name, field in FIELDS.items()},
                "include_byok_in_limit":data.get("include_byok_in_limit") if isinstance(data.get("include_byok_in_limit"),bool) else None,
                "limit_reset":data.get("limit_reset") if data.get("limit_reset") in {"daily","weekly","monthly"} else None}


class OpenRouterCosts:
    def __init__(self, home=None, fetch=fetch_key, resolve=configured_keys, clock=time.time):
        self.home = Path(home or Path.home())
        self.fetch = fetch
        self.resolve = resolve
        self.clock = clock
        self.cache = {}
        self.payload = {"meters": [], "unavailable_agents": ["openclaw", "hermes"], "checked_at": None}

    def refresh(self):
        now = self.clock()
        try:
            keys = self.resolve(self.home)
        except (OSError, ValueError, TypeError, AttributeError):
            # Do not show an old key's numbers if configuration can no longer be resolved.
            self.payload = {"meters": [], "unavailable_agents": ["openclaw", "hermes"], "checked_at": now}
            return
        groups = {}
        for agent, key in keys.items():
            if key:
                groups.setdefault(key, []).append(agent)
        meters = []
        live = set()
        for index, (key, agents) in enumerate(groups.items()):
            fingerprint = hashlib.sha256(key.encode()).hexdigest()
            live.add(fingerprint)
            old = self.cache.get(fingerprint, {})
            try:
                values = self.fetch(key)
                current = {**values, "updated_at": now, "state": "ready"}
            except Exception:
                # Network/HTTP/JSON errors can embed credentials; expose a fixed status only.
                current = {**old, "state": "stale" if old else "unavailable"}
            self.cache[fingerprint] = current
            meters.append({**current, "id": f"openrouter-{index + 1}", "agents": agents, "checked_at": now})
        self.cache = {k: v for k, v in self.cache.items() if k in live}
        self.payload = {
            "meters": meters,
            "unavailable_agents": [a for a, k in keys.items() if not k],
            "checked_at": now,
        }


def check_remaining(values, required_usd=0.0):
    """Fresh key-meter admission; unknown or stale account data is never permission.

    Caller fetches with the key actually bound to the Pi proxy, not a desktop agent's
    key. No credential is accepted or returned by this helper.
    """
    required = amount(required_usd)
    if required is None or values.get('state', 'ready') != 'ready':
        raise ValueError('OpenRouter budget is unavailable')
    remaining = amount(values.get('remaining_usd'))
    limit = amount(values.get('limit_usd'))
    if limit is not None and remaining is None:
        raise ValueError('OpenRouter remaining budget is unavailable')
    if remaining is not None and required > remaining:
        raise ValueError('OpenRouter account cap would be exceeded')
    if amount(values.get('lifetime_usd')) is None:
        raise ValueError('OpenRouter spending data is unavailable')
    return remaining
