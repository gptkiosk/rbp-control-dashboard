"""Project types: the list the new-project dialog offers, and a suggestion for a brief."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

import project_types
from deps import get_session  # noqa: F401  (kept for symmetry with other routers)
from settings import get_settings

router = APIRouter(prefix="/api/project-types")


class SuggestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=60000)


@router.get("")
def types(request: Request):
    return {"types": project_types.listing(get_settings())}


@router.post("/suggest")
def suggest(body: SuggestIn, request: Request):
    return {"suggested": project_types.suggest(body.text, get_settings())}
