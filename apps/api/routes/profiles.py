import secrets
import time
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from deps import get_session
from settings import get_settings
from auth import digest
import approval
import profiles
from typing import Literal
router=APIRouter(prefix='/api/profile')

class SecretIn(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    value: SecretStr=Field(min_length=8,max_length=4000)

class Appearance(BaseModel):
    model_config=ConfigDict(extra='forbid')
    theme:Literal['system','light','dark']

@router.patch('/appearance')
def appearance(body:Appearance,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'))
    row=profiles.get(s,identity);pref=profiles.prefs(s,identity);pref.theme=body.theme
    row.preferences=pref.model_dump_json();s.commit();return {'theme':body.theme}

@router.get('')
def read(request:Request,s:Session=Depends(get_session)):
    s.execute(text('BEGIN IMMEDIATE'))
    result=profiles.payload(s,profiles.owner(request))
    result['origins']=list(get_settings().auth_origins)
    try:
        from alerts import load_rules
        rules,_=load_rules(get_settings().alerts_path)
        destination=rules.destination
        result['suggested_discord_channel']=destination.removeprefix('discord:') if destination.startswith('discord:') else ''
    except (OSError,ValueError):pass
    s.commit();return result

@router.patch('/setup')
def setup(body:profiles.SetupProgress,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'))
    row=profiles.get(s,identity);pref=profiles.prefs(s,identity)
    pref.setup=body;row.preferences=pref.model_dump_json()
    s.commit();return profiles.payload(s,identity)

@router.put('')
def save(body:profiles.Preferences,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'))
    if body.working_dir and not approval.resolve_workdir(body.working_dir,get_settings().workdir_roots): raise HTTPException(422,'Choose an allowlisted working directory.')
    if body.dashboard_origin and body.dashboard_origin not in get_settings().auth_origins: raise HTTPException(422,'Choose one of this installation’s configured sign-in origins.')
    row=profiles.get(s,identity)
    old=profiles.prefs(s,identity)
    if body.use_saved_openrouter_key and not old.use_saved_openrouter_key:
        if not profiles.credential(s,identity,'openrouter',get_settings()): raise HTTPException(422,'Save your OpenRouter key first.')
        if any(o!=identity for o in profiles.saved_key_owners(s)): raise HTTPException(409,'Another operator already shares a saved OpenRouter key with the agents. Turn that off first.')
    if old.discord_channel_id!=body.discord_channel_id: row.discord_user_id=None;row.pair_hash=None;row.pair_expires=None
    row.preferences=body.model_dump_json();s.commit();return profiles.payload(s,identity)

def _bootstrap_readiness(settings):
    from agents import REGISTRY
    from native_routes import read as read_native
    from role_pack import RoleStore, RoleError
    checks=[]
    try:
        installed=REGISTRY['hermes'].available(settings)
    except Exception:
        installed=False
    checks.append({'id':'hermes','label':'Hermes is installed','ready':installed,'link':'/profile#agent-tools'})
    try:
        roles=RoleStore(settings).status()
        coordinator=roles.get('delegator')=='hermes'
        guidance=bool(roles.get('guidance_installed'))
    except (RoleError,OSError,ValueError):
        coordinator=False;guidance=False
    checks.append({'id':'coordinator','label':'Hermes is the assigned Coordinator','ready':coordinator,'link':'/profile#agent-roles'})
    checks.append({'id':'guidance','label':'Hermes Coordinator guidance is installed' if guidance else 'Apply Hermes Coordinator guidance','ready':guidance,'link':'/profile#agent-roles'})
    try:
        model=read_native(settings).get('hermes',{}).get('default')
    except Exception:
        model=None
    checks.append({'id':'model','label':'Hermes has a configured default model','ready':bool(model),'link':'/profile#agent-tools'})
    return {'ready':all(item['ready'] for item in checks),'checks':checks}

@router.get('/coordinator-bootstrap/readiness')
def coordinator_bootstrap_readiness(request:Request):
    profiles.owner(request)
    return _bootstrap_readiness(get_settings())

@router.post('/coordinator-bootstrap/start',status_code=201)
def start_coordinator_bootstrap(request:Request,s:Session=Depends(get_session)):
    """Create a reviewable setup project draft. This never starts a model run."""
    identity=profiles.owner(request);settings=get_settings();readiness=_bootstrap_readiness(settings)
    if not readiness['ready']:
        missing=[item['label'] for item in readiness['checks'] if not item['ready']]
        raise HTTPException(409,{'message':'Finish Hermes setup before starting agent configuration.','missing':missing,'checks':readiness['checks']})
    pref=profiles.prefs(s,identity);choice=pref.coordinator_bootstrap
    from pathlib import Path
    import projects
    working_dir=''
    scratch=projects.scratch_root(settings)
    if choice.project_workspaces and scratch is not None:
        working_dir=str(scratch)
    elif pref.working_dir:
        working_dir=pref.working_dir
    else:
        working_dir=next((str(Path(root).expanduser()) for root in settings.workdir_roots if Path(root).expanduser().is_dir()),'')
    if not working_dir:
        raise HTTPException(409,{'message':'Choose or enable an allowed project workspace before starting setup.','checks':readiness['checks'],'link':'/profile#settings'})
    platforms=', '.join(choice.platforms) or 'none selected'
    roles=', '.join(choice.roles) or 'none selected'
    memory='enabled' if choice.shared_project_memory else 'disabled unless needed and approved'
    workspaces='enabled' if choice.project_workspaces else 'use existing allowed workspaces only'
    model_policy='reuse each platform’s configured default; ask before any model change' if choice.model_policy=='ask_before_change' else 'reuse each platform’s configured default; do not change models without operator approval'
    prefix=settings.product_short_name.lower()
    brief=(f"Prepare this {settings.product_short_name} installation to receive and run projects using its installed agent platforms. "
        "First inspect platform readiness and the existing agent configurations. Keep Hermes as the sole Coordinator for this setup. "
        f"Consider only these operator-selected platforms: {platforms}. Configure these starter roles where supported: {roles}. "
        f"For OpenClaw, create missing agents named {prefix}-oc-developer and {prefix}-oc-security when those roles are selected, and {prefix}-oc-reviewer only if reviewer is selected. Give each a focused SOUL.md and a concise starting prompt that explains its specialty and how it reports findings to Hermes. "
        f"Shared project memory: {memory}. Project workspaces: {workspaces}. Model policy: {model_policy}. "
        f"Security review policy: {choice.security_review}. Create missing role agents/configuration where safe, but preserve every existing user configuration and agent; never overwrite or delete existing files/agents. "
        "Do not request or expose credentials, change billing, or execute actions that need operator approval. Identify unavailable platforms and model/sign-in prerequisites as human tasks with direct in-app links. "
        "Use the normal project plan and approval workflow. Return a concise readiness summary, proposed changes, human actions, and a small validation plan. Do not claim setup is complete until each change is verified.")
    from project_schemas import Document
    from sqlalchemy import text
    from native_routes import read as read_native
    hermes_model=read_native(settings).get('hermes',{}).get('default') or ''
    s.execute(text('BEGIN IMMEDIATE'))
    doc=Document(title=f'{settings.product_short_name} agent platform bootstrap',brief=brief,
        constraints='Hermes only for coordination. No agent work starts until the operator reviews and approves the project plan. Preserve existing configuration; create only missing role agents and guidance. Keep human-only sign-in, credentials, billing and permission changes as linked manual tasks.',
        working_dir=working_dir,planner_agent='hermes',planner_model=hermes_model,planning_bias=pref.planning_bias,nodes=[])
    project=projects.create(s,doc.model_dump(),settings,identity);s.commit()
    return {'project_id':project.id,'title':doc.title,'state':'draft','readiness':readiness}

@router.put('/credentials/{provider}')
def secret(provider:str,body:SecretIn,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'))
    profiles.put_credential(s,identity,provider,body.value.get_secret_value(),get_settings());s.commit();return profiles.payload(s,identity)

@router.delete('/credentials/{provider}')
def remove(provider:str,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);row=s.get(profiles.UserCredential,(identity,provider))
    if row:s.delete(row)
    if provider=='openrouter':   # no key, no sharing: the switch goes off with it
        pref=profiles.prefs(s,identity)
        if pref.use_saved_openrouter_key: pref.use_saved_openrouter_key=False;profiles.get(s,identity).preferences=pref.model_dump_json()
    s.commit();return profiles.payload(s,identity)

@router.post('/discord/pair')
def pair(request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'));row=profiles.get(s,identity)
    if not profiles.prefs(s,identity).discord_channel_id:raise HTTPException(422,'Save a Discord channel first.')
    profiles.bridge_token(get_settings(),True)
    code=secrets.token_hex(8).upper();row.pair_hash=digest(code);row.pair_expires=int(time.time())+600;s.commit()
    return {'code':code,'expires_in_seconds':600,'instruction':'Send this code to Hermes in your saved Discord channel: Link my MCD profile with code '+code}

@router.post('/discord/unlink')
def unlink(request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);row=profiles.get(s,identity);row.discord_user_id=None;row.pair_hash=None;row.pair_expires=None;s.commit();return profiles.payload(s,identity)

@router.post('/openrouter/check')
def spending(request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request)
    key=profiles.credential(s,identity,'openrouter',get_settings())
    if not key:raise HTTPException(422,'Save your OpenRouter key first.')
    from openrouter_costs import fetch_key
    try:return {'spending':fetch_key(key),'checked_at':int(time.time())}
    except Exception:raise HTTPException(503,'OpenRouter spending is unavailable. Your key was not displayed.') from None
