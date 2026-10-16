"""Bounded model-output contract. Plans are data, never commands or authorization."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Route(Strict):
    agent: Literal['claude', 'codex', 'grok', 'hermes', 'openclaw']
    model: str = Field(min_length=1, max_length=120)

class Node(Strict):
    key: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    kind: Literal['phase', 'story'] = 'story'
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=12000)
    acceptance: str = Field(default='', max_length=6000)
    scope: str = Field(default='', max_length=3000)
    parent: str | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    assignee: Literal['human', 'claude', 'codex', 'grok', 'hermes', 'openclaw'] = 'codex'
    model: str = Field(default='', max_length=120)
    agent_target: str = Field(default='', max_length=80)
    mode: Literal['read', 'edit'] = 'read'
    rationale: str = Field(default='', max_length=2000)
    fallbacks: list[Literal['claude','codex','grok']] = Field(default_factory=list, max_length=3)
    routes: list[Route] = Field(default_factory=list, max_length=6)
    # Standard job envelope for stories (see job_envelope.py). `work_kind` is the kind of work; `kind` above is phase|story.
    # A plan is refused at approval when a story lacks work_kind, size, risk, estimate_minutes or route_reason.
    work_kind: Literal['research', 'plan', 'implement', 'review', 'test', 'docs', 'ops', 'triage'] | None = None
    size: Literal['xs', 's', 'm', 'l', 'xl'] | None = None
    risk: Literal['low', 'medium', 'high'] | None = None
    area: str = Field(default='', max_length=40, pattern=r'^([a-z0-9][a-z0-9._-]{0,39})?$')
    estimate_minutes: int | None = Field(default=None, ge=1, le=100000)
    route_reason: str = Field(default='', max_length=300)
    assignee_user: str = Field(default='', max_length=120, pattern=r'^([A-Za-z0-9][A-Za-z0-9._@+-]{0,119})?$')  # for human stories: who they are for
    # Used only when the project builds in parallel (see project_schedule.py). `touches` lists the files or folders a story changes, so two stories
    # that can run together can be checked for overlap; `integration` marks a story that joins the branches of the stories it depends on.
    touches: list[str] = Field(default_factory=list, max_length=20)
    integration: bool = False

    @field_validator('touches')
    @classmethod
    def safe_touches(cls, value):
        import re
        for item in value:
            if not re.fullmatch(r'[A-Za-z0-9._/*?\[\]-]{1,120}', item) or item.startswith('/') or '..' in item.split('/'):
                raise ValueError('touches must be relative file or folder patterns inside the project')
        return value

    @field_validator('parent', mode='before')
    @classmethod
    def empty_parent(cls, value): return value or None

    x: float = Field(default=0, ge=0, le=10000)
    y: float = Field(default=0, ge=0, le=10000)

DEFAULT_PLANNING_BIAS = 50

class Document(Strict):
    title: str = Field(min_length=1, max_length=200)
    brief: str = Field(min_length=1, max_length=20000)
    constraints: str = Field(default='', max_length=10000)
    working_dir: str = Field(min_length=1, max_length=500)
    planner_agent: Literal['auto', 'claude', 'codex', 'grok', 'hermes', 'openclaw'] = 'auto'
    planner_model: str = Field(default='', max_length=120)
    planning_bias: int = Field(default=DEFAULT_PLANNING_BIAS, ge=0, le=100, strict=True)
    dispatch_mode: Literal['sequential','parallel'] = 'sequential'
    nodes: list[Node] = Field(default_factory=list, max_length=100)

class Save(Strict):
    revision: int = Field(ge=1)
    document: Document

class Action(Strict):
    revision: int = Field(ge=1)
    approve_coordination: bool = False
    delegator_revision: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    approve_api_planning: bool = False
    approve_api_work: bool = False

class Close(Strict):
    revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=300)

class Retry(Action):
    route: Route | None = None

class ContinueOutput(Strict):
    revision: int = Field(ge=1)
    run_id: int = Field(ge=1)
    approve_output: bool = False

class Note(Strict):
    text: str = Field(min_length=1, max_length=12000)

class Accept(Strict):
    revision: int | None = Field(default=None, ge=1)
    run_id: int | None = None
    summary: str = Field(min_length=1, max_length=12000)
    snapshot: bool = False
    files: list[str] = Field(default_factory=list, max_length=500)
    output_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class HandoffPolicy(Strict):
    revision: int = Field(ge=1)
    manifest_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    mode: Literal['manual', 'batch', 'automatic']
    approve: bool = False

class Retier(Strict):
    revision: int = Field(ge=1)
    claude_model: Literal['claude-haiku-5-5', 'claude-sonnet-5-5'] = 'claude-haiku-5-5'
    codex_model: Literal['gpt-6-luna', 'gpt-5.6-terra'] = 'gpt-6-luna'
    acknowledge: bool = False

class RepairExecution(Strict):
    revision: int = Field(ge=1)
    acknowledge: bool = False


class GoFree(Strict):
    revision: int = Field(ge=1)
    run_id: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=120)
    agent_target: str = Field(min_length=1, max_length=80)


class ModelLock(Strict):
    revision: int = Field(ge=1)
    enabled: StrictBool
