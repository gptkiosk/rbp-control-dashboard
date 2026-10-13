"""Health endpoint. The only route that stays public once auth lands."""

from __future__ import annotations

import os
import time

from fastapi import APIRouter

from settings import get_settings
from version import __version__, git_sha

router = APIRouter()

_STARTED = time.monotonic()


@router.get("/healthz")
def healthz() -> dict[str, object]:
    settings = get_settings()
    data_dir = settings.data_dir
    return {
        "status": "ok",
        "version": __version__,
        "git_sha": git_sha(),
        "uptime_s": round(time.monotonic() - _STARTED, 1),
        "data_dir_writable": data_dir.is_dir() and os.access(data_dir, os.W_OK),
        "web_built": (settings.web_dist / "index.html").is_file(),
    }
