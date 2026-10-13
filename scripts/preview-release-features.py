#!/usr/bin/env python3
"""Loopback fixture UI for release reconciliation. No real operator or mutation routes exist here."""
import argparse, json, sys, time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--port',required=True,type=int)
p.add_argument('--data-dir',required=True,type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'apps/api'))
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from spa import mount_spa
from version import git_sha, __version__
import guard, uvicorn
product=json.loads((root/'packaging/product.json').read_text())['product']
repo='gptkiosk/'+('mac-control-dashboard' if product=='mcd' else 'rbp-control-dashboard')
data=a.data_dir.absolute()
if data.name != 'synthetic-release-preview': p.error('Use a fresh folder named synthetic-release-preview.')
data.mkdir(parents=True,exist_ok=True,mode=0o700)
app=FastAPI(docs_url=None,redoc_url=None)
started=time.monotonic()
current={'id':'fixture-current','version':'0.2.7','channel':'stable','complete':True,'change':'install','repository':repo,'authenticity':'synthetic fixture','staged_at':0}
@app.middleware('http')
async def safety(request:Request,call_next):
 reason=guard.check(request,(a.port,))
 if reason: return guard.refusal(reason)
 if request.method not in guard.SAFE_METHODS and request.url.path!='/api/agent-installs/plan':
  return JSONResponse({'detail':'Fixture preview: installations, updates, credentials and all mutations are disabled.'},status_code=403)
 return await call_next(request)
@app.get('/auth/status')
def auth(): return {'enabled':True,'user':{'email':'synthetic-preview@example.invalid','method':'fixture','expires_at':0},'local_recovery':False}
@app.get('/healthz')
def health(): return {'status':'ok','preview':True,'version':__version__,'git_sha':git_sha(),'web_git_sha':git_sha(),'git_dirty':True,'uptime_s':time.monotonic()-started,'data_dir_writable':True,'web_built':True,'environment':'synthetic preview','product_name':product.upper()+' fixture preview','product_short_name':product.upper(),'organization_name':'Synthetic data'}
@app.get('/api/profile')
def profile(): return {'owner':'synthetic-preview@example.invalid','preferences':{'theme':'system','planning_bias':50,'working_dir':'','dashboard_origin':'','discord_channel_id':'','notify_plans':False,'allow_discord_planning':False,'allow_discord_control':False,'allow_discord_diagnostics':False,'setup':{'step':6,'status':'complete','confirmed':[]}},'discord_linked':False,'discord_user_id':None,'credentials':[],'origins':[]}
@app.get('/api/workdirs')
def workdirs(): return {'workdirs':[]}
@app.get('/api/app-updates')
def updates(): return {'kind':'release','detail':'Synthetic packaged install (no real service)','configured':True,'problems':[],'manual_instructions':[],'blockers':[],'install':{'current':'fixture-current','previous':None,'tx':None,'last':None,'needs_recovery':False,'versions':[current]}}
@app.get('/api/app-updates/check')
def check(): return {'available':True,'installed':'0.2.7','candidate':{'product':product,'platform':'darwin-arm64' if product=='mcd' else 'linux-arm64','repository':repo,'channel':'stable','tag':'v0.3.0','version':'0.3.0','change':'upgrade','prerelease':False,'notes':'SYNTHETIC PREVIEW: Grok and any mix of installed agents. This endpoint never contacts GitHub.','html_url':f'https://github.com/{repo}/releases','published_at':'2026-10-13T00:00:00Z','manifest_sha256':None,'archive_sha256':None,'assets':[],'authenticity':'Synthetic fixture; no downloadable package'}}
if product=='rcd':
 import tool_install as ti
 cfg=ti.ToolsConfig(root=data/'tools',catalog_dir=root/'apps/api',platform_key='linux-arm64',home=data,product='rcd')
 catalog=ti.load_catalog(cfg.catalog_dir)
 facts=ti.HostFacts(system='Linux',machine='aarch64',pointer_bits=64,os_name='Synthetic Linux arm64 (not Pi hardware)',os_family='debian',euid=1000,mem_total_mb=4096,mem_available_mb=3072,disk_free_mb=20480,commands={c:f'/usr/bin/{c}' for c in ti.PROBED_COMMANDS})
 @app.get('/api/agent-installs')
 def tools():
  body=ti.inspect(cfg,catalog,facts);body.update(log=[],notes={t:catalog.component(t).get('note') for t in catalog.tool_ids()});return body
 @app.post('/api/agent-installs/plan')
 async def plan(request:Request):
  body=await request.json()
  try: return ti.build_plan(cfg,catalog,facts,body['tool'],body['action'])
  except (ti.ToolError,KeyError) as e: return JSONResponse({'detail':str(e)},status_code=422)
@app.get('/api/{rest:path}')
def unsupported(rest:str): return JSONResponse({'detail':'This feature is outside the fixture preview.'},status_code=503)
mount_spa(app,root/'apps/web/dist')
uvicorn.run(app,host='127.0.0.1',port=a.port)
