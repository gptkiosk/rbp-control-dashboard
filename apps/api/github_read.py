"""Bounded optional GitHub reads. This module never reads or exports tokens."""
from __future__ import annotations
import asyncio, copy, json, re, subprocess, threading, time
from github_config import GithubConfigStore, SLUG
REPO_FIELDS = "{name: .full_name, description: .description, private: .private, archived: .archived, updated_at: .updated_at, branch: .default_branch}"
ITEM_FIELDS = "[.[] | {number: .number, title: .title, user: .user.login, updated_at: .updated_at, draft: (.draft // false), is_pull: (.pull_request != null), labels: [.labels[].name]}]"
LOGIN = re.compile(r"account ([A-Za-z0-9-]+)")
class GithubUnavailable(Exception): pass
class GithubReader:
 def __init__(self,binary,config=None):self.binary=binary;self.config_store=config;self.cache={};self.lock=threading.RLock();self.last_manual=0.0
 def status(self):return self.config_store.status() if self.config_store else {"state":"ready","configured":True}
 def config(self):return self.config_store.config() if self.config_store else None
 def auth_status(self):
  """Scoped status only; it deliberately never calls `gh auth token`."""
  try:
   result=subprocess.run([self.binary,"auth","status","--hostname","github.com","--active"],capture_output=True,text=True,timeout=5,check=False);text=(result.stdout or "")+(result.stderr or "");match=LOGIN.search(text);return {"available":result.returncode==0,"account":match.group(1) if match else ""}
  except (OSError,subprocess.TimeoutExpired):return {"available":False,"account":""}
 def query(self,endpoint,fields,object_result=False):
  try:
   result=subprocess.run([self.binary,"api","--method","GET",endpoint,"--jq",fields],capture_output=True,timeout=12,check=False)
   if result.returncode or len(result.stdout)>4*1024*1024:raise GithubUnavailable()
   value=json.loads(result.stdout)
   if not isinstance(value,dict if object_result else list):raise GithubUnavailable()
   return value
  except (OSError,subprocess.TimeoutExpired,ValueError):raise GithubUnavailable() from None
 def cached(self,key,loader,force=False):
  with self.lock:
   old=self.cache.get(key)
   if old and not force and time.monotonic()-old[0]<60:return copy.deepcopy(old[1])
   try:value={**loader(),"checked_at":time.time(),"error":None,"stale":False}
   except (GithubUnavailable,KeyError,TypeError):value=copy.deepcopy(old[1]) if old else {"checked_at":None};value.update(error="GitHub is unavailable. Check the configured gh login, repository access or rate limit.",stale=True)
   self.cache[key]=(time.monotonic(),value);return copy.deepcopy(value)
 def _disabled(self):return {"repos":[],"limited":False,"checked_at":None,"stale":False,"error":None,"setup":self.status()}
 def repos(self,force=False):
  config=self.config()
  if self.config_store and config is None:return self._disabled()
  if config is None:
   def legacy():
    raw=self.query("user/repos?per_page=100&sort=updated","[.[] | "+REPO_FIELDS+"]");repos=[]
    for item in raw[:100]:
     if not isinstance(item,dict) or not isinstance(item.get("name"),str) or not SLUG.fullmatch(item["name"]):raise GithubUnavailable()
     repos.append({**item,"url":"https://github.com/"+item["name"]})
    return {"repos":repos,"limited":len(raw)>=100}
   result=self.cached("repos",legacy,force);result.setdefault("repos",[]);result.setdefault("limited",False);return result
  allowed=config.repos if config else ();public_only=config.public_only if config else False
  def load():
   repos=[]
   for name in allowed:
    item=self.query(f"repos/{name}",REPO_FIELDS,object_result=True)
    if item.get("name")!=name or not isinstance(item.get("private"),bool):raise GithubUnavailable()
    if not (public_only and item["private"]):repos.append({**item,"url":"https://github.com/"+name})
   return {"repos":repos,"limited":False}
  result=self.cached(("repos",allowed,public_only),load,force);result.setdefault("repos",[]);result.setdefault("limited",False);return result
 def details(self,name,force=False):
  config=self.config()
  if self.config_store and (config is None or name not in config.repos):return None
  if not SLUG.fullmatch(name) or (config is None and name not in {r["name"] for r in self.repos()["repos"]}):return None
  if config and config.public_only:
   repo=self.query(f"repos/{name}",REPO_FIELDS,object_result=True)
   if repo.get("private"):return None
  def items(kind,cap):
   raw=self.query(f"repos/{name}/{kind}?state=open&per_page={cap}&sort=updated&direction=desc",ITEM_FIELDS)
   if any(not isinstance(row,dict) for row in raw):raise GithubUnavailable()
   selected=[row for row in raw if kind=="pulls" or not row.get("is_pull")];output=[]
   for row in selected[:50]:
    if not isinstance(row.get("number"),int) or row["number"]<=0:raise GithubUnavailable()
    output.append({**row,"url":f"https://github.com/{name}/{'pull' if kind=='pulls' else 'issues'}/{row['number']}"})
   return {"items":output,"limited":len(raw)>=cap or len(selected)>50}
  return {"name":name,"pulls":self.cached((name,"pulls"),lambda:items("pulls",50),force),"issues":self.cached((name,"issues"),lambda:items("issues",100),force)}
 def refresh(self,manual=False):
  config=self.config()
  if self.config_store and config is None:return self._disabled()
  if manual:
   with self.lock:
    if time.monotonic()-self.last_manual<30:return self.repos()
    self.last_manual=time.monotonic()
  return self.repos(force=True)
 async def poll(self,stop):
  while not stop.is_set():
   config=self.config()
   if config is None:return
   self.refresh()
   try:await asyncio.wait_for(stop.wait(),timeout=config.poll_seconds)
   except asyncio.TimeoutError:pass
