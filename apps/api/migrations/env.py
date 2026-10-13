"""Alembic environment. The connection is passed in by migrate.py (no URL in alembic.ini)."""

from __future__ import annotations

from alembic import context

import models  # noqa: F401 - registers tables on Base.metadata
from db import Base

target_metadata = Base.metadata
connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("run migrations through migrate.py, which supplies the connection")

context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
