import json
from types import SimpleNamespace
import github_read
from github_config import GithubConfigStore
from github_read import GithubReader

def test_absent_or_disabled_config_never_invokes_gh(tmp_path,monkeypatch):
 calls=[];monkeypatch.setattr(github_read.subprocess,"run",lambda *a,**k:calls.append(a) or SimpleNamespace(returncode=0,stdout=b"[]",stderr=b""))
 store=GithubConfigStore(tmp_path/"data");reader=GithubReader("fake-gh",store)
 assert reader.repos()["setup"]["state"]=="migration_required"
 store.save({"version":1,"enabled":False,"account":"","repos":[],"public_only":False,"poll_seconds":900})
 assert reader.repos()["setup"]["state"]=="disabled" and calls==[]

def test_explicit_config_is_allowlisted_and_public_only(tmp_path,monkeypatch):
 store=GithubConfigStore(tmp_path/"data");store.save({"version":1,"enabled":True,"account":"operator","repos":["good/public","good/private"],"public_only":True,"poll_seconds":900});calls=[]
 def run(argv,**kwargs):
  calls.append(argv);name=argv[4].removeprefix("repos/");return SimpleNamespace(returncode=0,stdout=json.dumps({"name":name,"private":name.endswith("private"),"archived":False}).encode(),stderr=b"")
 monkeypatch.setattr(github_read.subprocess,"run",run);reader=GithubReader("fake-gh",store)
 assert [r["name"] for r in reader.repos()["repos"]]==["good/public"]
 assert all("good/" in call[4] and "user/repos" not in call[4] for call in calls) and reader.details("other/private") is None

def test_config_is_0600_and_has_no_secrets(tmp_path):
 store=GithubConfigStore(tmp_path/"data");status=store.save({"version":1,"enabled":True,"account":"operator","repos":["good/public"],"public_only":False,"poll_seconds":900});raw=(tmp_path/"data"/"github.json").read_text()
 assert "token" not in raw.lower() and status["secrets_stored"] is False and (tmp_path/"data"/"github.json").stat().st_mode&0o777==0o600
