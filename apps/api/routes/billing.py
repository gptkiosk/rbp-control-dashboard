from typing import Annotated, Literal
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field, ConfigDict, StringConstraints
from sqlalchemy.orm import Session
from deps import get_session
from models import BillingConfig
import billing
import media_catalog

router = APIRouter(prefix="/api")


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["api", "subscription"]
    monthly_usd: float = Field(ge=0, le=10000)


class Rate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    input: float = Field(ge=0, le=10000)
    output: float = Field(ge=0, le=10000)
    cached: float = Field(ge=0, le=10000)
    write: float = Field(ge=0, le=10000)
    write_1h: float = Field(ge=0, le=10000)
    max_input: int | None = Field(default=None, ge=1)


class LimitsPatch(BaseModel):
    """Spending limits: all off unless set here, the one place to set them."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    require_reviewed_pricing: bool | None = None
    per_run_cap_usd: float | None = Field(default=None, ge=0, le=100000)      # 0 or empty: no cap
    paid_needs_runtime_limit: bool | None = None


class BillingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limits: LimitsPatch | None = None
    # Your own price for a media model (USD per image or per second); null clears it and the listed price applies again.
    media_rates: dict[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)], float | None] = Field(default_factory=dict, max_length=100)
    accounts: dict[Literal["openclaw", "hermes", "claude", "codex", "grok"], Account] = Field(
        default_factory=dict, max_length=5
    )
    rates: dict[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
        ],
        Rate,
    ] = Field(default_factory=dict, max_length=100)


@router.get("/media/models")
def media_models(s: Session = Depends(get_session)):
    """The media-model catalog with the operator's own prices applied, and whether a fal key is saved (never the key)."""
    from sqlalchemy import select
    from models import UserCredential
    saved = s.scalar(select(UserCredential.owner).where(UserCredential.provider == "fal").limit(1)) is not None
    return {**media_catalog.catalog(s), "fal_key_saved": saved}


@router.get("/billing")
def get_billing(s: Session = Depends(get_session)):
    return billing.config(s)


@router.patch("/billing")
def patch_billing(body: BillingPatch, s: Session = Depends(get_session)):
    row = s.get(BillingConfig, 1)
    old = json.loads(row.payload) if row else {}
    old["accounts"] = {
        **old.get("accounts", {}),
        **{a: c.model_dump() for a, c in body.accounts.items()},
    }
    if body.limits is not None:
        sent = body.limits.model_fields_set
        merged = dict(old.get("limits") or {})
        for key in ("require_reviewed_pricing", "paid_needs_runtime_limit"):
            if key in sent and getattr(body.limits, key) is not None:
                merged[key] = getattr(body.limits, key)
        if "per_run_cap_usd" in sent:
            cap = body.limits.per_run_cap_usd
            merged["per_run_cap_usd"] = cap if cap and cap > 0 else None
        old["limits"] = merged
    if body.media_rates:
        known = {m["id"] for m in media_catalog.MODELS}
        mine = dict(old.get("media_rates") or {})
        for model, price in body.media_rates.items():
            if model not in known:
                raise HTTPException(422, f"Unknown media model: {model}")
            if price is None:
                mine.pop(model, None)
            elif price < 0 or price > 10000 or price != price:
                raise HTTPException(422, "A media price must be between 0 and 10000 USD.")
            else:
                mine[model] = price
        old["media_rates"] = mine
    old["rates"] = {
        **old.get("rates", {}),
        **{m: {**r.model_dump(), "source": "custom"} for m, r in body.rates.items()},
    }
    if row:
        row.payload = json.dumps(old)
    else:
        s.add(BillingConfig(id=1, payload=json.dumps(old)))
    s.commit()
    return billing.config(s)


@router.get("/agents/usage")
def usage_dashboard(
    request: Request,
    period: Literal["24h", "7d", "month"] = "month",
    agent: Literal["openclaw", "hermes", "claude", "codex", "grok"] | None = None,
    target: str | None = Query(default=None, max_length=160),
    s: Session = Depends(get_session),
):
    result = billing.dashboard(s, period, agent, target)
    collector = request.app.state.collector
    result["coverage"] = collector.usage_scanner.status if collector else {}
    result["openrouter"] = (
        collector.openrouter_costs.payload if collector else
        {"meters": [], "unavailable_agents": ["openclaw", "hermes"], "checked_at": None}
    )
    return result
