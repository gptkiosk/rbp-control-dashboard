from typing import Annotated, Literal
import json
from fastapi import APIRouter, Depends, Request, Query
from pydantic import BaseModel, Field, ConfigDict, StringConstraints
from sqlalchemy.orm import Session
from deps import get_session
from models import BillingConfig
import billing

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


class BillingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accounts: dict[Literal["openclaw", "hermes", "claude", "codex", "grok"], Account] = Field(
        default_factory=dict, max_length=5
    )
    rates: dict[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
        ],
        Rate,
    ] = Field(default_factory=dict, max_length=100)


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
