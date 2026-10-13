"""Subscription limit status and the operator's reroute choice."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

import provider_limits
from deps import get_session

router = APIRouter(prefix="/api/limits")


class Reroute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("")
def get_limits(s: Session = Depends(get_session)):
    return provider_limits.payload(s, int(time.time()))


@router.post("/{provider}/reroute")
def set_reroute(provider: Literal["claude", "codex"], body: Reroute, s: Session = Depends(get_session)):
    now = int(time.time())
    if provider_limits.set_reroute(s, provider, body.enabled, now) is None:
        raise HTTPException(404, "No active limit for this provider.")
    s.commit()
    return provider_limits.payload(s, now)
