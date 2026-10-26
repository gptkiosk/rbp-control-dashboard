"""Source-independent API observations. Data only; never routes, prices for billing, or instructions."""
import ipaddress
import json
import math
import os
import tempfile
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, model_validator
from typing import Literal

_LOCK = threading.RLock()
MAX_RECORDS = 3000
LITELLM_URL = 'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json'
UNITS = {'input_price': 'USD/M tokens', 'output_price': 'USD/M tokens', 'latency_p50': 'ms',
         'output_speed': 'tokens/s', 'context': 'tokens', 'max_output': 'tokens',
         'quality': 'score', 'tools': 'boolean', 'vision': 'boolean', 'structured': 'boolean'}


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,119}$')
    metric: Literal['input_price','output_price','latency_p50','output_speed','context','max_output','quality','tools','vision','structured']
    value: StrictBool | StrictInt | StrictFloat
    unit: str = Field(max_length=20)
    source: str = Field(max_length=200)
    as_of: date
    benchmark: str = Field(default='',max_length=100,pattern=r'^[^\x00-\x1f\x7f]*$')
    scale_max: StrictInt | StrictFloat | None = None
    environment: str = Field(default='',max_length=80,pattern=r'^[^\x00-\x1f\x7f]*$')
    method: str = Field(default='',max_length=160,pattern=r'^[^\x00-\x1f\x7f]*$')

    @model_validator(mode='after')
    def bounded(self):
        url=urlsplit(self.source)
        host=url.hostname or ''
        if url.scheme!='https' or not host or '.' not in host or url.username or url.password or url.fragment or url.query:
            raise ValueError('Use a public HTTPS source URL without credentials, query parameters or fragments.')
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError('Use the public source hostname, not an IP address.')
        if host.endswith(('.local','.localhost','.internal','.ts.net')):
            raise ValueError('Use a public model-data source.')
        if self.as_of>datetime.now(timezone.utc).date(): raise ValueError('Observation dates cannot be in the future.')
        if self.unit!=UNITS[self.metric]: raise ValueError('Use the documented unit for this metric.')
        boolean=self.metric in {'tools','vision','structured'}
        if isinstance(self.value,bool)!=boolean: raise ValueError('Capability values are boolean; measurement values are numeric.')
        if not boolean and (not math.isfinite(self.value) or not 0<=self.value<=1e12): raise ValueError('Measurement is outside the supported range.')
        if self.metric in {'context','max_output'} and (type(self.value) is not int or self.value<=0): raise ValueError('Token limits need a positive integer.')
        if self.metric=='quality' and (not self.benchmark or self.scale_max is None or self.scale_max<=0 or self.value>self.scale_max):
            raise ValueError('Quality needs a named/versioned benchmark and its positive score scale.')
        if self.scale_max is not None and (self.metric!='quality' or isinstance(self.scale_max,bool) or not math.isfinite(self.scale_max) or not 0<self.scale_max<=1e12):
            raise ValueError('Invalid benchmark scale.')
        return self


def records(data_dir):
    from model_profiles import _read_json
    raw=_read_json(Path(data_dir)/'models/evidence.json')
    if not isinstance(raw,list): return []
    rows=[]
    for item in raw[:MAX_RECORDS]:
        try: rows.append(Observation.model_validate(item).model_dump(mode='json'))
        except (ValueError,TypeError): continue
    return rows


def ingest(data_dir, observations):
    """An authenticated operator/import adapter submits normalized facts. No URL is fetched."""
    def key(row): return tuple(row[k] for k in ('model','metric','source','benchmark','environment','method'))
    with _LOCK:
        current={key(row):row for row in records(data_dir)}
        changed=0
        for item in observations:
            row=item.model_dump(mode='json'); previous=current.get(key(row))
            if previous and previous['as_of']>row['as_of']: continue
            if previous!=row: current[key(row)]=row; changed+=1
        if len(current)>MAX_RECORDS: raise ValueError('Model data store is full; review sources before importing more.')
        path=Path(data_dir)/'models/evidence.json'
        if path.is_symlink() or path.parent.is_symlink(): raise ValueError('Model data must use the private regular data directory.')
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
                temporary=Path(f.name);json.dump(list(current.values()),f);f.flush();os.fsync(f.fileno())
            os.chmod(temporary,0o600);os.replace(temporary,path)
        finally:
            if temporary and temporary.exists():temporary.unlink()
    return {'changed':changed,'records':len(current),'routes_changed':False,'billing_changed':False}


def for_model(all_records, model, now):
    rows=[r for r in all_records if r['model']==model]
    out=[]
    for row in sorted(rows,key=lambda r:r['as_of'],reverse=True)[:8]:
        peers=[r for r in rows if all(r[k]==row[k] for k in ('metric','benchmark','environment','method','unit','scale_max'))]
        out.append({**row,'stale':now-datetime.fromisoformat(row['as_of']).replace(tzinfo=timezone.utc).timestamp()>90*86400,
                    'conflicting':any(r['value']!=row['value'] for r in peers)})
    return out


def refresh_litellm(data_dir, fetch=None):
    """One fixed public JSON source; no arbitrary URL, provider key, prices or routes changed."""
    import billing
    from model_profiles import default_fetch, MAX_BYTES
    data=(fetch or (lambda:default_fetch(LITELLM_URL)))()
    if len(data)>MAX_BYTES:raise ValueError('Reference map exceeds the supported size.')
    raw=json.loads(data)
    if not isinstance(raw,dict):raise ValueError('Reference map is not a model object.')
    candidates=set(billing.CATALOG.get('models',{}))|set(billing.CATALOG.get('free_models',{}))
    observations=[]
    fields={'input_cost_per_token':('input_price',1e6),'output_cost_per_token':('output_price',1e6),
            'max_input_tokens':('context',1),'max_output_tokens':('max_output',1),
            'supports_vision':('vision',1),'supports_function_calling':('tools',1),'supports_response_schema':('structured',1)}
    for model in sorted(candidates):
        row=raw.get(model) or raw.get('openrouter/'+model)
        if not isinstance(row,dict):continue
        for field,(metric,multiplier) in fields.items():
            value=row.get(field)
            if type(value) not in (int,float,bool):continue
            if metric not in {'vision','tools','structured'}:
                if isinstance(value,bool):continue
                value=value*multiplier
            try:
                observations.append(Observation(model=model,metric=metric,value=value,unit=UNITS[metric],source=LITELLM_URL,
                    as_of=datetime.now(timezone.utc).date(),environment='Reference API catalog; verify provider terms',
                    method='LiteLLM published JSON retrieved on as_of; not provider verification'))
            except ValueError:continue
    if not observations:raise ValueError('No supported model facts were found in the reference map.')
    return {**ingest(data_dir,observations),'source':LITELLM_URL,'observations':len(observations),
            'note':'Reference data only. Billing catalog and active model routes were not changed.'}
