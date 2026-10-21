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

@router.get('/route-reliability')
def route_reliability(request:Request,s:Session=Depends(get_session)):
    import route_reliability as recovery
    return recovery.payload(s,get_settings(),profiles.owner(request))

from route_reliability import RecoveryPolicy

@router.put('/route-reliability')
def save_route_reliability(body:RecoveryPolicy,request:Request,s:Session=Depends(get_session)):
    import route_reliability as recovery
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'))
    available={(r['agent'],r['model']) for r in recovery.options(s,get_settings())}
    if any((r.agent,r.model) not in available for r in body.routes):
        raise HTTPException(422,'Choose configured models from the current route list.')
    pref=profiles.prefs(s,identity);pref.route_recovery=body
    profiles.get(s,identity).preferences=pref.model_dump_json();s.commit()
    return recovery.payload(s,get_settings(),identity)

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

class SetupApply(BaseModel):
    digest:str=Field(pattern=r'^[0-9a-f]{16}$')

def _setup_error(exc):
    return HTTPException(exc.status,str(exc))

@router.get('/coordinator-bootstrap/setup')
def coordinator_setup(request:Request,s:Session=Depends(get_session)):
    """What setup checks and would change now. Read-only."""
    import agent_setup
    identity=profiles.owner(request)
    return agent_setup.plan(get_settings(),s,profiles.prefs(s,identity))

@router.post('/coordinator-bootstrap/setup/apply')
def apply_coordinator_setup(body:SetupApply,request:Request,s:Session=Depends(get_session)):
    """Make exactly the previewed changes. Existing agents and files are never changed."""
    import agent_setup
    identity=profiles.owner(request)
    try:
        return agent_setup.apply(get_settings(),s,profiles.prefs(s,identity),body.digest)
    except agent_setup.SetupError as exc:
        raise _setup_error(exc)

@router.post('/coordinator-bootstrap/start',status_code=201)
def start_coordinator_bootstrap(request:Request,s:Session=Depends(get_session)):
    """Create the small validation project once setup is verified. This never starts a model run by itself."""
    import agent_setup
    identity=profiles.owner(request);settings=get_settings();readiness=_bootstrap_readiness(settings)
    s.execute(text('BEGIN IMMEDIATE'))
    from models import Project
    from sqlalchemy import select
    import projects
    existing=s.scalar(select(Project).where(Project.created_by==identity,Project.intake_key.like('bootstrap:%'),
        Project.state.notin_(['closed','complete'])).order_by(Project.id.desc()).limit(1))
    if existing:
        return {'project_id':existing.id,'title':projects.document(existing)['title'],'state':existing.state,'readiness':readiness,'existing':True}
    if not readiness['ready']:
        missing=[item['label'] for item in readiness['checks'] if not item['ready']]
        raise HTTPException(409,{'message':'Finish Hermes setup before starting agent configuration.','missing':missing,'checks':readiness['checks']})
    pref=profiles.prefs(s,identity);setup=agent_setup.plan(settings,s,pref)
    if not setup['verified']:
        raise HTTPException(409,{'message':'Finish platform setup first: apply the changes or fix the items listed.','problems':setup['problems'],'link':'/profile#coordinator-bootstrap'})
    nodes=agent_setup.validation_nodes(s,settings,setup)
    if len(nodes)<2:
        raise HTTPException(409,{'message':'No ready platform can run a validation story.','link':'/profile#coordinator-bootstrap'})
    ready=', '.join(c['name'] for c in setup['checks'] if c['state']=='ready')
    brief=(f"Validate the {settings.product_short_name} agent platforms that Coordinator setup verified: {ready}. "
        "Each platform gets one read-only story that proves it answers on its configured route. Then the operator reviews the reports and starts a real project.")
    from project_schemas import Document, Node
    from native_routes import read as read_native
    hermes_model=read_native(settings).get('hermes',{}).get('default') or ''
    doc=Document(title=f'{settings.product_short_name} agent platform validation',brief=brief,
        constraints='Read-only validation. No files, configuration, credentials, billing or permissions change.',
        working_dir=setup['base'],planner_agent='hermes',planner_model=hermes_model,planning_bias=pref.planning_bias,nodes=[])
    doc.nodes=[Node.model_validate(n) for n in nodes]
    project=projects.create(s,doc.model_dump(),settings,identity)
    prepared=projects.document(project)
    projects.pin_free_routes(s,prepared,settings)
    projects.add_recovery_routes(s,project,prepared,settings)
    import json
    project.document=json.dumps(prepared)
    project.intake_key=f'bootstrap:{project.id}'
    project.state='review'
    projects.memory(s,project,'proposal','Built-in validation plan prepared by Coordinator setup without a provider call. Review and submit it to run one read-only story per ready platform.',identity)
    s.commit()
    return {'project_id':project.id,'title':doc.title,'state':'review','readiness':readiness}

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
    return {'code':code,'expires_in_seconds':600,'instruction':'Send this code to Hermes in your saved Discord channel: Link my RCD profile with code '+code}

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
