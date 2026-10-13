"""Release envelope for the footer."""

from __future__ import annotations

from fastapi import APIRouter, Request

from migrate import migrations_pending
from settings import get_settings
from version import __version__, git_sha

router = APIRouter(prefix="/api")


@router.get("/release")
def release(request: Request) -> dict[str, object]:
    settings = get_settings()
    return {
        "version": __version__,
        "environment": settings.environment,
        "commit_sha": git_sha(),
        "has_migrations": migrations_pending(request.app.state.engine),
        "owner": settings.organization_name,
        "product": settings.product_name,
        "product_short": settings.product_short_name,
    }
