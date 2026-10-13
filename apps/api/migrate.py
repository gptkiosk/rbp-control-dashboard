"""Run Alembic migrations against the app's database (called at startup)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

API_DIR = Path(__file__).resolve().parent


def _config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    return cfg


def upgrade_to_head(engine: Engine) -> None:
    cfg = _config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def migrations_pending(engine: Engine) -> bool:
    """True when the database is behind the newest migration (shown in the footer)."""
    head = ScriptDirectory.from_config(_config()).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current != head
