"""Fail-closed, free-only model admission (SEC-013 for the $0 OpenRouter test policy).

A model is admitted only if an operator-supplied pricing snapshot lists that exact id with every
price field equal to zero and the snapshot is recent. Unknown, unpriced, malformed or stale
entries are refused; nothing here ever estimates a positive allowance.

Snapshot file (JSON)::

    {"verified_at": 1760000000, "source": "https://openrouter.ai/api/v1/models",
     "models": {"vendor/model:free": {"prompt": "0", "completion": "0", "request": "0"}}}

``snapshot_from_openrouter_models`` builds that structure from the public ``GET /models`` payload
(no API key needed). It is a pure function; fetching is the operator's explicit action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import time
from typing import Any, Mapping

PRICE_FIELDS = ("prompt", "completion", "request", "image", "web_search", "internal_reasoning",
                "input_cache_read", "input_cache_write")
DEFAULT_MAX_AGE_S = 24 * 3600


class Refusal(Exception):
    """A request was refused before any provider call. ``code`` is an adapter_contract error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _price(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    price = Decimal(str(value))
    if not price.is_finite() or price < 0:
        raise InvalidOperation
    return price


@dataclass(frozen=True)
class FreeModelCatalog:
    models: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    verified_at: int = 0
    source: str = ""
    max_age_s: int = DEFAULT_MAX_AGE_S

    @classmethod
    def load(cls, path: Path, *, max_age_s: int = DEFAULT_MAX_AGE_S) -> "FreeModelCatalog":
        try:
            raw = json.loads(Path(path).read_text())
            return cls(dict(raw["models"]), int(raw["verified_at"]), str(raw.get("source", "")), max_age_s)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Refusal("BUDGET_EXCEEDED", "Free-model pricing snapshot is missing or malformed") from exc

    def admit(self, model: str, *, now: float | None = None) -> None:
        """Return None if ``model`` is verified zero-priced, else raise Refusal."""
        if not model or not isinstance(model, str):
            raise Refusal("MODEL_NOT_ALLOWED", "No model assigned")
        age = (time.time() if now is None else now) - self.verified_at
        if self.verified_at <= 0 or age > self.max_age_s or age < -300:
            raise Refusal("BUDGET_EXCEEDED", "Free-model pricing snapshot is stale or undated")
        pricing = self.models.get(model)
        if pricing is None:  # not a free route at all, as opposed to a listed model with a bad price
            raise Refusal("MODEL_NOT_ALLOWED", "Model is not in the verified free-model snapshot")
        if not isinstance(pricing, Mapping):
            raise Refusal("BUDGET_EXCEEDED", "Model price is malformed")
        if "prompt" not in pricing or "completion" not in pricing:
            raise Refusal("BUDGET_EXCEEDED", "Model price is unknown")
        try:
            prices = [_price(pricing[k]) for k in PRICE_FIELDS if k in pricing]
        except (InvalidOperation, ValueError):
            raise Refusal("BUDGET_EXCEEDED", "Model price is malformed") from None
        if any(p != 0 for p in prices):
            raise Refusal("BUDGET_EXCEEDED", "Model is not zero-priced; paid spend is not authorised")


def snapshot_from_openrouter_models(payload: Mapping[str, Any], *, now: int | None = None) -> dict[str, Any]:
    """Keep only models whose every advertised price is exactly zero."""
    models: dict[str, dict[str, str]] = {}
    for entry in payload.get("data", []):
        pricing = entry.get("pricing")
        if not isinstance(pricing, Mapping) or "prompt" not in pricing or "completion" not in pricing:
            continue
        try:
            if all(_price(v) == 0 for v in pricing.values()):
                models[str(entry["id"])] = {k: str(v) for k, v in pricing.items()}
        except (InvalidOperation, ValueError, KeyError):
            continue
    return {"verified_at": int(time.time() if now is None else now),
            "source": "https://openrouter.ai/api/v1/models", "models": models}
