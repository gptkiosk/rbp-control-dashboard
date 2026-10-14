#!/usr/bin/env python3
"""Read-only snapshot of the side-by-side MCD/Mission Control run. No sign-in or sends."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None
opener=urllib.request.build_opener(NoRedirect)
def http(url, health=False):
    try:
        with opener.open(url,timeout=5) as response:
            return {"reachable":True,"status":response.status,**({"health":json.loads(response.read(4096))} if health else {})}
    except urllib.error.HTTPError as error:
        return {"reachable":True,"status":error.code}
    except (OSError, ValueError):
        return {"reachable":False,"status":None}

def job(label):
    try:
        result=subprocess.run(["launchctl","print",f"gui/{os.getuid()}/{label}"],capture_output=True,text=True,timeout=5)
        fields={}
        if result.returncode: return {"loaded":False}
        for line in result.stdout.splitlines():
            if line.startswith("\t") and not line.startswith("\t\t") and " = " in line:
                key,value=line.strip().split(" = ",1)
                if key in ("state","pid","runs","last exit code"): fields[key]=value
        return {"loaded":True,**fields}
    except (OSError,subprocess.TimeoutExpired): return {"loaded":False}

now=int(time.time())
report={"checked_at":datetime.now(timezone.utc).isoformat(),
        "mcd":http("http://127.0.0.1:8800/healthz",True),
        "mission_control":http("http://127.0.0.1:3000/"),
        "mcd_job":job("com.operator.mac-control"),
        "mission_control_job":job("com.openclaw.mission-control")}
root=Path.home()/".mac-control"
try:
    with sqlite3.connect((root/"data.db").as_uri()+"?mode=ro",uri=True) as db:
        latest=db.execute("select max(ts) from metric_sample").fetchone()[0]
        samples=db.execute("select count(*) from metric_sample where ts >= ?",(now-1800,)).fetchone()[0]
        stages=dict(db.execute("select stage,count(*) from run group by stage"))
        tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        alerts=dict(db.execute("select status,count(*) from alert_event group by status")) if 'alert_event' in tables else {}
        report["data"]={"sample_age_seconds":None if latest is None else now-latest,
            "samples_last_30_minutes":samples,"run_stages":stages,"alert_states":alerts}
except sqlite3.Error: report["data"]={"error":"Runtime database unavailable"}
report["ops_reports"]={"present":Path(os.getenv("MAC_CONTROL_OPS_REPORTS_DIR",str(Path.home()/".mac-control/reports"))).is_dir()}
print(json.dumps(report,indent=2))
