"""Throwaway server stand-in for crash tests: runs a dispatcher until it is SIGKILLed.

Not a test module. No socket, credential or outbound call. Usage: crash_host.py <db_path> <data_dir>
"""
import asyncio
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from db import make_engine, make_session_factory  # noqa: E402
from dispatcher import Dispatcher  # noqa: E402
from tests.test_dispatcher import _registry, _settings  # noqa: E402


async def main(db_path: str, data_dir: str) -> None:
    sessions = make_session_factory(make_engine(Path(db_path)))
    d = Dispatcher(sessions, _settings(Path(data_dir)), registry=_registry(), poll_s=0.1)
    d.start()
    await asyncio.sleep(3600)


asyncio.run(main(*sys.argv[1:3]))
