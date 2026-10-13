"""Crash tests use only tracked disposable PIDs and migrated temporary databases."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from db import durable_sessions
from dispatcher import Dispatcher
from agents import RunMeta
from models import Card, ProviderReceipt, Run, UsageRecord
import project_outputs
from tests.test_dispatcher import _card, _registry, _settings, SUCCESS


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    pytest.fail('Disposable chaos worker did not reach expected state')


@pytest.mark.parametrize('failure', ['api', 'runtime', 'finished_while_down'])
def test_sigkill_recovery_one_completion_artifact_and_receipt(sessions, tmp_path, failure):
    now = int(time.time())
    with sessions.begin() as db:
        db.add(Card(id=1, title='chaos', body='synthetic', agent='synthetic', mode='read',
            working_dir=str(tmp_path), column='queued', position=1, timeout_s=30,
            needs_approval=False, created_by='test', created_at=now, updated_at=now))
    worker = Path(__file__).with_name('durable_worker.py')
    processes = []
    def launch():
        proc = subprocess.Popen([sys.executable, str(worker), 'host', str(tmp_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        processes.append(proc)
        return proc
    try:
        first = launch()
        wait_until(lambda: (tmp_path / 'runtime.pid').exists())
        def spawned():
            with sessions() as db:
                run = db.scalar(select(Run))
                return run is not None and run.pid is not None and db.scalar(select(func.count()).select_from(ProviderReceipt)) == 1
        wait_until(spawned)
        with sessions() as db:
            original = db.scalar(select(Run))
            key = original.idempotency_key
        first.kill()  # only the Popen PID created by this test
        first.wait(timeout=5)
        if failure == 'runtime':
            runtime_pid = int((tmp_path / 'runtime.pid').read_text())
            os.kill(runtime_pid, signal.SIGKILL)  # PID reported by our synthetic child
            wait_until(lambda: (tmp_path / 'runs' / 'run-1.exit').exists())
        elif failure == 'finished_while_down':
            (tmp_path / 'release').touch()
            wait_until(lambda: (tmp_path / 'runs' / 'run-1.exit').exists())
        second = launch()
        (tmp_path / 'release').touch()
        wait_until(lambda: (tmp_path / 'done').exists())
        second.wait(timeout=5)
        assert second.returncode == 0, second.stderr.read().decode()
        with sessions() as db:
            runs = list(db.scalars(select(Run).order_by(Run.id)))
            assert sum(r.stage == 'succeeded' for r in runs) == 1
            assert all(r.idempotency_key == key for r in runs)
            assert db.get(Card, 1).column == 'done'
            assert db.scalar(select(func.count()).select_from(ProviderReceipt)) == 1
            assert db.scalar(select(func.count()).select_from(UsageRecord)) == 1
            assert db.execute(text('PRAGMA integrity_check')).scalar_one() == 'ok'
            if failure == 'runtime':
                assert [r.stage for r in runs] == ['interrupted', 'succeeded']
                assert runs[1].attempt == 2 and runs[1].requeued_from == runs[0].id
            else:
                assert len(runs) == 1
        artifacts = list((tmp_path / 'project-outputs').rglob('*.md'))
        assert len(artifacts) == 1 and artifacts[0].read_text() == 'one artifact'
        assert not list((tmp_path / 'project-outputs').rglob('*.tmp'))
    finally:
        (tmp_path / 'release').touch()
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            proc.stderr.close()
        # Only groups recorded by this test's private DB; never look up ports.
        with sessions() as db:
            for run in db.scalars(select(Run)):
                if run.pid:
                    from legacy_adapters import supervisor_alive
                    if supervisor_alive(run.pid, str(tmp_path / 'runs' / f'run-{run.id}.exit')):
                        try: os.killpg(run.pid, signal.SIGKILL)
                        except ProcessLookupError: pass


def test_wal_and_fsync_policy(sessions):
    with sessions() as db:
        assert db.execute(text('PRAGMA journal_mode')).scalar() == 'wal'
        assert db.execute(text('PRAGMA synchronous')).scalar() == 1
    with durable_sessions(sessions)() as db:
        assert db.execute(text('PRAGMA synchronous')).scalar() == 2
        assert db.execute(text('PRAGMA foreign_keys')).scalar() == 1


def test_upgrade_existing_database_preserves_history(tmp_path):
    from alembic import command
    from db import make_engine
    from migrate import _config, upgrade_to_head
    engine = make_engine(tmp_path / 'old.db')
    try:
        with engine.begin() as connection:
            cfg = _config()
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, '0011')
            connection.execute(text("""INSERT INTO run
                (agent, stage, started_at, working_dir, command, log_path)
                VALUES ('synthetic', 'succeeded', 1, '/synthetic', '[]', '')"""))
        upgrade_to_head(engine)
        upgrade_to_head(engine)  # startup migrations are replay safe
        with engine.connect() as connection:
            assert connection.execute(text('SELECT stage, attempt, idempotency_key FROM run')).one() == ('succeeded', 1, None)
            assert connection.execute(text('SELECT count(*) FROM provider_receipt')).scalar() == 0
            assert connection.execute(text('PRAGMA integrity_check')).scalar() == 'ok'
    finally:
        engine.dispose()


def test_retry_spec_keeps_execution_key(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    first, rid = d._claim(1)[0]
    d.recover('synthetic crash')
    retry, rid2 = d._claim(1)[0]
    assert first['adapter_spec']['idempotency_key'] == retry['adapter_spec']['idempotency_key']
    assert retry['adapter_spec']['attempt'] == 2 and rid != rid2


def test_failed_adapter_recovery_never_requeues_or_claims(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    d._claim(1)
    async def unavailable():
        raise RuntimeError('cannot verify liveness')
    d.adapters['fake'].recover = unavailable
    with pytest.raises(RuntimeError): asyncio.run(d.tick())
    with sessions() as db:
        assert db.get(Card, cid).column == 'running'
        assert db.scalar(select(func.count()).select_from(Run)) == 1


def test_receipt_replay_across_attempts_is_one_ledger_entry(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    _card(sessions, tmp_path, SUCCESS)
    _, rid = d._claim(1)[0]
    receipt = dict(response_id='response1', model='synthetic:free', ts=1,
        usage=dict(input_tokens=2, output_tokens=1), cost_usd=0.125)  # fabricated test data; no spend
    event = dict(type='usage', data=dict(provider_receipts=[receipt, receipt]))
    d._adapter_event(rid, 'fake', event)
    d.recover('synthetic')
    _, retry_id = d._claim(1)[0]
    d._adapter_event(retry_id, 'fake', event)
    d._finish(retry_id, 1, 'succeeded', 0, None, RunMeta(cost_usd=0.125), 1)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(UsageRecord)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderReceipt)) == 1
        assert db.get(Run, rid).cost_usd == 0.125
        assert db.get(Run, retry_id).cost_usd == 0


def test_process_identity_denial_fails_closed(monkeypatch):
    import legacy_adapters
    import psutil
    from adapter_contract import AdapterError
    def denied(_): raise psutil.AccessDenied(123)
    monkeypatch.setattr(psutil, 'Process', denied)
    with pytest.raises(AdapterError): legacy_adapters.supervisor_alive(123, 'private-exit-path')


def test_checkpoint_event_is_durable(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    _card(sessions, tmp_path, SUCCESS)
    _, rid = d._claim(1)[0]
    d._adapter_event(rid, 'fake', dict(type='checkpoint', seq=4,
        data=dict(checkpoint_id='synthetic-checkpoint')))
    with sessions() as db:
        checkpoint = json.loads(db.get(Run, rid).checkpoint)
        assert checkpoint['event_seq'] == 4
        assert checkpoint['adapter_checkpoint']['checkpoint_id'] == 'synthetic-checkpoint'


def test_recovery_result_survives_a_later_adapter_failure(sessions, tmp_path):
    from tests.test_dispatcher_adapter_bridge import StubAdapter
    adapter = StubAdapter()
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry(), adapters={'fake': adapter})
    cid = _card(sessions, tmp_path, SUCCESS)
    _, rid = d._claim(1)[0]
    calls = 0
    async def recovered_once():
        nonlocal calls
        calls += 1
        return [dict(run_id=str(rid), outcome='finished_while_down')] if calls == 1 else []
    adapter.recover = recovered_once
    class InitiallyUnavailable:
        name = 'unavailable'
        async def recover(self):
            if calls == 1: raise RuntimeError('temporary recovery error')
            return []
    d.adapters['unavailable'] = InitiallyUnavailable()
    async def run():
        with pytest.raises(RuntimeError): await d.tick()
        assert await d.tick() == 0
        await asyncio.gather(*d._tasks.values())
    asyncio.run(run())
    assert not adapter.specs  # replayed result; start was never called
    with sessions() as db:
        assert db.get(Run, rid).stage == 'succeeded'
        assert db.get(Card, cid).column == 'done'


def test_artifact_concurrent_replay_and_crash_temp(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path)
    target = project_outputs.save(settings, 1, 1, 1, 'key', 'content')
    target.with_name('.key.md.tmp').write_text('partial crash data')
    def write(_): return project_outputs.save(settings, 1, 1, 1, 'key', 'content')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(write, range(16))) == [target] * 16
    assert target.read_text() == 'content'
    assert not target.with_name('.key.md.tmp').exists()


def test_completion_is_serialized_and_db_constrained(sessions, tmp_path):
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    cid = _card(sessions, tmp_path, SUCCESS)
    _, rid = d._claim(1)[0]
    with sessions() as db:
        key = db.get(Run, rid).idempotency_key
    with pytest.raises(IntegrityError), sessions.begin() as db:
        db.add(Run(agent='fake', stage='running', started_at=1, working_dir=str(tmp_path),
                   command='[]', log_path='', idempotency_key=key))
    def finish(_): d._finish(rid, cid, 'succeeded', 0, None, RunMeta(result_text='OK'), 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(finish, range(8)))
    with sessions.begin() as db:
        db.add(Run(card_id=cid, agent='fake', stage='running', started_at=1,
            working_dir=str(tmp_path), command='[]', log_path='', idempotency_key=key))
        db.flush()
        duplicate = db.scalar(select(Run).where(Run.stage == 'running')).id
    d._finish(duplicate, cid, 'succeeded', 0, None, RunMeta(result_text='duplicate'), 1)
    with sessions() as db:
        assert db.get(Run, duplicate).stage == 'failed'
        assert db.scalar(select(func.count()).select_from(Run).where(Run.stage == 'succeeded')) == 1


def test_sigkill_db_writer_preserves_commits_and_rolls_back_open_transaction(sessions, tmp_path):
    """Abrupt process death with a FULL WAL commit and uncommitted pages.

    This is not a hardware power cut: the OS and storage continue running.
    """
    worker = tmp_path / 'writer.py'
    worker.write_text('''import sqlite3, sys, time
from pathlib import Path
root = Path(sys.argv[1])
db = sqlite3.connect(root / 'test.db')
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA synchronous=FULL')
db.execute('CREATE TABLE crash_probe (id INTEGER PRIMARY KEY, payload TEXT)')
db.execute("INSERT INTO crash_probe VALUES (1, 'committed')")
db.commit()
db.execute('BEGIN IMMEDIATE')
db.executemany('INSERT INTO crash_probe VALUES (?, ?)', [(n, 'x'*8192) for n in range(2, 500)])
(root / 'writer-ready').touch()
while True: time.sleep(.1)
''')
    proc = subprocess.Popen([sys.executable, str(worker), str(tmp_path)])
    try:
        wait_until(lambda: (tmp_path / 'writer-ready').exists())
        proc.kill()
        proc.wait(timeout=5)
        with sessions() as db:
            assert db.execute(text('PRAGMA integrity_check')).scalar_one() == 'ok'
            assert db.execute(text('SELECT id, payload FROM crash_probe')).all() == [(1, 'committed')]
        with durable_sessions(sessions).begin() as db:
            db.execute(text("INSERT INTO crash_probe VALUES (2, 'restart commit')"))
    finally:
        if proc.poll() is None: proc.kill()
        proc.wait(timeout=5)
