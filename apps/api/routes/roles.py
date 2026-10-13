"""Operator-only, preview-bound role assignment. Never called on behalf of agents."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from role_pack import RoleStore, RoleError
from routes.agent_tools import operator
from settings import get_settings

router = APIRouter(prefix='/api/roles')
class Assignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    roles: dict[str, str]
    workspace: str = Field(default='', max_length=500)
class Apply(Assignment):
    plan_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm: bool = False
class Rollback(BaseModel):
    confirm: bool = False

def call(fn):
    try:
        return fn(RoleStore(get_settings()))
    except (RoleError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from None

@router.get('')
def status(request: Request):
    operator(request)
    return call(lambda store: store.status())

@router.post('/preview')
def preview(request: Request, body: Assignment):
    operator(request)
    return call(lambda store: store.preview(body.roles, body.workspace)[1])

@router.post('/apply')
def apply(request: Request, body: Apply):
    operator(request)
    if not body.confirm:
        raise HTTPException(422, 'Review and confirm the role instruction changes.')
    return call(lambda store: store.apply(body.roles, body.workspace, body.plan_sha256))

@router.post('/rollback')
def rollback(request: Request, body: Rollback):
    operator(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm rollback of the last role assignment.')
    return call(lambda store: store.rollback())

@router.post('/recover')
def recover(request: Request, body: Rollback):
    operator(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm recovery of the interrupted role assignment.')
    return call(lambda store: store.recover())
