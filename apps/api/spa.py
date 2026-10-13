"""Serve the built Vue app from the API process.

One process and one port: /api/* and /healthz are API routes; /assets/* are
static files from the Vite build; any other GET returns index.html so Vue
Router can handle client-side routes. Unknown /api/* paths stay JSON 404s.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles



# Browsers expect the web app manifest as application/manifest+json.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def _is_api_path(path: str) -> bool:
    return path in ("/api", "/healthz") or path.startswith("/api/")


def mount_spa(app: FastAPI, dist: Path) -> None:
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):  # noqa: ARG001 - path is routed, not read
        path = request.url.path
        if _is_api_path(path):
            raise HTTPException(status_code=404, detail="Not found")
        # Files at the dist root (favicon, icons) are served directly.
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        if not index.is_file():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Web app is not built. Run `npm run build` in apps/web.",
                },
            )
        return FileResponse(index)
