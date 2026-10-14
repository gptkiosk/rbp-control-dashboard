"""SQLite engine and session factory.

WAL mode lets the collector write while API requests read. The database lives
in the data dir (~/.mac-control/data.db), never in the repo.

SD-card settings: synchronous=NORMAL fsyncs only at WAL checkpoints, so frequent
metric writes do not wear the card; in WAL mode it cannot corrupt the database, but
a power cut may roll back the newest commits. Run-lifecycle commits (claim, finish,
interrupt/requeue) are rare and use `durable_sessions` (synchronous=FULL) so they
survive power loss (subject to the storage device honoring fsync). journal_size_limit
limits retained WAL space when SQLite resets the journal, and
temp_store=MEMORY keeps sort/temp files off the card.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

WAL_SIZE_LIMIT = 64 * 1024 * 1024


class Base(DeclarativeBase):
    pass


def make_engine(db_path: Path | str, durable: bool = False) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
        # Durable sessions are short and rare; unpooled connections avoid leaking handles.
        **({"poolclass": NullPool} if durable else {}),
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - exercised via every connect
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA synchronous={'FULL' if durable else 'NORMAL'}")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT}")
        cur.execute("PRAGMA wal_autocheckpoint=1000")  # batch ~4 MiB at the default page size
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def durable_sessions(sessions: sessionmaker) -> sessionmaker:
    """Sessions on the same database whose commits are fsynced (synchronous=FULL)."""
    bind = sessions.kw.get("bind")
    database = getattr(getattr(bind, "url", None), "database", None)
    if not database or database == ":memory:" or bind.url.get_backend_name() != "sqlite":
        return sessions
    return make_session_factory(make_engine(database, durable=True))
