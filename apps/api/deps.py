"""Request-scoped access to app state (sessions, collector)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


def get_collector(request: Request):
    return request.app.state.collector
