"""Keys and access: what each key is for, whether it is in place, and what a project seems to need before it is created."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

import key_registry
import profiles
from agents import REGISTRY
from deps import get_session
from settings import get_settings

router = APIRouter(prefix="/api/keys")


def available_agents():
    settings = get_settings()
    return [name for name, spec in REGISTRY.items() if spec.available(settings)]


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=60000)


@router.get("")
def keys(request: Request, s: Session = Depends(get_session)):
    return key_registry.registry(s, profiles.owner(request), available_agents())


@router.post("/check")
def check(body: CheckIn, request: Request, s: Session = Depends(get_session)):
    return key_registry.needs(s, profiles.owner(request), body.text, available_agents())
