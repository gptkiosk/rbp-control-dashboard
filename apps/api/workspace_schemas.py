"""Operator/paired channel handoffs share the same bounded input contract."""
from pydantic import BaseModel, ConfigDict, Field


class Reservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    working_dir: str = Field(default='', max_length=500)
    snapshot: str = Field(pattern=r'^[a-f0-9]{64}$')
    operation_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    label: str = Field(default='Coding app', min_length=1, max_length=80)


class Handoff(Reservation):
    reservation_id: str | None = Field(default=None, pattern=r'^[a-f0-9-]{32,36}$')
    summary: str = Field(min_length=3, max_length=6000)
