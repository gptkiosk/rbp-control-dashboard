#!/usr/bin/env python3
"""Loopback-only synthetic report UI; no DB, workers, credentials or host dotenv.

Run with the API virtualenv Python. This deliberately limited preview app uses
the production report routes and SPA, with a synthetic operator for folder QA.
Never deploy it as the dashboard service.
"""
import argparse
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-dir", required=True, type=Path)
parser.add_argument("--port", required=True, type=int)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
# The preview cannot inherit the production service environment or dotenv.
for key in list(os.environ):
    if key.startswith("MAC_CONTROL_"):
        del os.environ[key]
from settings import Settings, DEFAULT_DATA_DIR
from report_storage import ReportStorage
from routes.operations import router
from spa import mount_spa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import guard
import uvicorn

data = args.data_dir.absolute()
if not data.is_absolute() or data == DEFAULT_DATA_DIR or (data / "data.db").exists():
    parser.error("Use a separate preview directory without a dashboard database.")
data.mkdir(parents=True, mode=0o700, exist_ok=True)
reports = data / "reports"
approved = data / "approved-reports"
reports.mkdir(exist_ok=True)
approved.mkdir(exist_ok=True)
for folder in (reports, approved):
    sample = folder / "synthetic-preview.md"
    if not sample.exists():
        sample.write_text("# Synthetic report storage preview\n\nThis isolated UI uses a synthetic operator and local fixture reports. No production database, agent jobs, credentials or messaging are connected.\n\nSwitch to the approved folder or restore defaults to try the host storage workflow.\n")
settings = Settings(_env_file=None, data_dir=data, port=args.port,
                    collector_enabled=False, dispatcher_enabled=False,
                    reports_allowed_roots=(approved,), web_dist=root / "apps/web/dist")
started = time.monotonic()
app = FastAPI(docs_url=None, redoc_url=None)
app.state.reports = ReportStorage(settings)

@app.middleware("http")
async def preview_guard(request: Request, call_next):
    reason = guard.check(request, (args.port,))
    if reason:
        return guard.refusal(reason)
    if request.method not in guard.SAFE_METHODS and request.url.path != "/api/report-storage":
        return JSONResponse({"detail": "Only report storage changes are enabled in this preview."}, status_code=403)
    request.state.user = {"email": "preview@example.invalid", "method": "preview"}
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.get("/auth/status")
def auth_status():
    return {"enabled": False, "user": {"email": "preview@example.invalid", "method": "preview", "expires_at": 0}, "local_recovery": False}

@app.get("/healthz")
def health():
    return {"status": "ok", "preview": True, "version": "0.1.0", "git_sha": "synthetic-preview",
            "uptime_s": time.monotonic() - started, "data_dir_writable": True,
            "web_built": (settings.web_dist / "index.html").is_file()}

# Only report endpoints are installed; no agent, credential or messaging services.
for route in router.routes:
    if route.path.startswith(("/api/reports", "/api/report-storage")):
        app.router.routes.append(route)
mount_spa(app, settings.web_dist)
uvicorn.run(app, host="127.0.0.1", port=args.port)
