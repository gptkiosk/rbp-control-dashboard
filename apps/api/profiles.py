"""Per-operator settings. Provider keys are encrypted and never returned to callers."""
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Literal
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from models import UserProfile, UserCredential

PROVIDERS = ('openrouter','discord')
class SetupProgress(BaseModel):
    model_config = ConfigDict(extra='forbid')
    step: int = Field(default=0, ge=0, le=6, strict=True)
    status: Literal['new','in_progress','deferred','complete'] = 'new'
    confirmed: list[Literal['host','native_routes','subscriptions','tour']] = Field(default_factory=list,max_length=4)

class GithubPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    public_only: bool = False
    repos: list[str] = Field(default_factory=list,max_length=100)
    @field_validator('repos')
    @classmethod
    def github_repos(cls,value):
        import re
        if len(set(value))!=len(value) or any(not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',item) for item in value):raise ValueError('Invalid GitHub repository selection.')
        return value

class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    theme: Literal['system','light','dark'] = 'system'
    ai_agent: Literal['hermes','openclaw','claude','codex','grok'] = 'hermes'
    ai_model: str = Field(default='openrouter/free', min_length=1, max_length=200, pattern=r'^[^\s\x00-\x1f]+$')
    planning_bias: int = Field(default=50,ge=0,le=100,strict=True)
    working_dir: str = Field(default='',max_length=500)
    dashboard_origin: str = Field(default='',max_length=300)
    discord_channel_id: str = Field(default='',pattern=r'^([0-9]{16,22})?$')
    notify_plans: bool = True
    use_saved_openrouter_key: bool = False   # opt in: Hermes and OpenClaw run with this installation's saved OpenRouter key
    allow_discord_planning: bool = False
    allow_discord_control: bool = False
    allow_discord_diagnostics: bool = False
    github: GithubPreferences = Field(default_factory=GithubPreferences)
    setup: SetupProgress = Field(default_factory=SetupProgress)

    @field_validator('dashboard_origin')
    @classmethod
    def origin(cls,value):
        from urllib.parse import urlsplit
        from auth import loopback
        if not value: return value
        u=urlsplit(value)
        if u.scheme!='https' and not (u.scheme=='http' and loopback(u.hostname or '')): raise ValueError('Use HTTPS or HTTP loopback.')
        if not u.hostname or u.username or u.password or u.path or u.query or u.fragment: raise ValueError('Use an origin without path or credentials.')
        return value

def owner(request):
    if getattr(request.state,'agent_grant',None) or getattr(request.state,'project_bridge',False): raise HTTPException(403,'Operator profile access required.')
    user=getattr(request.state,'user',None)
    if request.app.state.auth.settings.auth_enabled and (not user or user['method']!='google'): raise HTTPException(403,'Sign in with Google to manage a profile.')
    return (user or {}).get('email','operator')

def get(s,identity):
    row=s.get(UserProfile,identity)
    if not row:
        row=UserProfile(owner=identity,preferences=Preferences().model_dump_json());s.add(row);s.flush()
    return row

def prefs(s,identity):
    row=s.get(UserProfile,identity)
    return Preferences.model_validate_json(row.preferences) if row else Preferences()

def private_file(path,create=None):
    """No symlinks, shared modes or replacement of an existing trust root."""
    path=Path(path)
    try:
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    except OSError: raise HTTPException(503,'Private credential storage is unavailable.') from None
    try:
        info=os.fstat(parent)
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700: raise ValueError()
        if create is not None:
            try:
                fd=os.open(path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                with os.fdopen(fd,'wb') as output: output.write(create);output.flush();os.fsync(output.fileno())
            except FileExistsError: pass
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        with os.fdopen(fd,'rb') as source:
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>4096: raise ValueError()
            return source.read()
    except (OSError,ValueError): raise HTTPException(503,'Private credential storage is unavailable; no plaintext fallback.') from None
    finally: os.close(parent)

def cipher(settings,create=False):
    try: return Fernet(private_file(settings.data_dir/'vault.key',Fernet.generate_key() if create else None).strip())
    except (ValueError,InvalidToken): raise HTTPException(503,'Private credential storage is unavailable.') from None

def credential(s,identity,provider,settings):
    row=s.get(UserCredential,(identity,provider))
    if not row: return None
    try: return cipher(settings).decrypt(row.ciphertext.encode()).decode()
    except (InvalidToken,UnicodeError): raise HTTPException(503,'Stored credential could not be decrypted.') from None

SAVED_KEY_AGENTS = ('hermes','openclaw')

def saved_key_owners(s):
    """Operators who shared their saved OpenRouter key with the agents (at most one is allowed)."""
    owners=[]
    for row in s.scalars(select(UserProfile)):
        try:
            if Preferences.model_validate_json(row.preferences).use_saved_openrouter_key: owners.append(row.owner)
        except ValueError: continue
    return owners

def saved_openrouter_key(s,settings):
    """The key to supply to Hermes and OpenClaw runs, or None. Off unless one operator opted in AND still has a key saved.
    Any failure to read it means no key is supplied: a run never fails, and never gets another credential, because of this."""
    owners=saved_key_owners(s)
    if len(owners)!=1: return None
    try: return credential(s,owners[0],'openrouter',settings)
    except HTTPException: return None

def put_credential(s,identity,provider,value,settings):
    if provider not in PROVIDERS: raise HTTPException(404,'Unknown credential provider.')
    raw=value.strip()
    if len(raw)<8 or any(c in raw for c in '\r\n\x00'): raise HTTPException(422,'Invalid credential.')
    get(s,identity)
    row=s.get(UserCredential,(identity,provider)) or UserCredential(owner=identity,provider=provider)
    row.ciphertext=cipher(settings,True).encrypt(raw.encode()).decode();row.hint=raw[-4:];s.add(row)

def payload(s,identity):
    row=get(s,identity)
    return {'owner':identity,'preferences':Preferences.model_validate_json(row.preferences).model_dump(),'discord_linked':bool(row.discord_user_id),'discord_user_id':row.discord_user_id,
        'credentials':[{'provider':r.provider,'hint':r.hint} for r in s.scalars(select(UserCredential).where(UserCredential.owner==identity))]}

def bridge_token(settings,create=False):
    return private_file(settings.data_dir/'agent-tokens/hermes-projects.token',(secrets.token_urlsafe(48)+'\n').encode() if create else None).decode().strip()
