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
    if old.discord_channel_id!=body.discord_channel_id: row.discord_user_id=None;row.pair_hash=None;row.pair_expires=None
    row.preferences=body.model_dump_json();s.commit();return profiles.payload(s,identity)

@router.put('/credentials/{provider}')
def secret(provider:str,body:SecretIn,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);s.execute(text('BEGIN IMMEDIATE'))
    profiles.put_credential(s,identity,provider,body.value.get_secret_value(),get_settings());s.commit();return profiles.payload(s,identity)

@router.delete('/credentials/{provider}')
def remove(provider:str,request:Request,s:Session=Depends(get_session)):
    identity=profiles.owner(request);row=s.get(profiles.UserCredential,(identity,provider))
    if row:s.delete(row)
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
