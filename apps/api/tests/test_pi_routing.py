from copy import deepcopy
import pytest
from adapter_contract import AdapterError
from pi_routing import ScopeCaps, admit
from openrouter_costs import check_remaining
from usage import put_provider_receipt
from billing import price, config
from models import UsageRecord, RunEvent
from sqlalchemy import select


def spec(tmp_path):
    return {'prompt': 'inspect source', 'workspace': {'path': str(tmp_path), 'mode': 'read'},
            'model_policy': {'assigned': {'agent': 'picoclaw', 'model': 'vendor/Exact:free'},
                             'allow_runtime_fallback': False},
            'budget': {'billing': 'unknown', 'max_cost_usd': 0}}


def test_verbatim_assignment_zero_cap_and_only_approved_routes(tmp_path):
    s = spec(tmp_path)
    route = deepcopy(s['model_policy']['assigned'])
    fallback = {'agent': 'zeroclaw', 'model': 'vendor/fallback:free'}
    result = admit(s, ScopeCaps(0, 0), [route, fallback], roots=(tmp_path,))
    assert result['model_policy']['assigned'] == route
    assert result['budget'] == {'billing': 'free', 'max_cost_usd': 0}
    assert result['model_policy']['approved_fallback_routes'] == [fallback]
    assert result['model_policy']['allow_runtime_fallback'] is False


@pytest.mark.parametrize('mutation,code', [
    ('model', 'MODEL_NOT_ALLOWED'), ('fallback', 'MODEL_NOT_ALLOWED'),
    ('cap', 'BUDGET_EXCEEDED'), ('spend', 'BUDGET_EXCEEDED'),
])
def test_reject_before_dispatch(tmp_path, mutation, code):
    s = spec(tmp_path)
    routes = [deepcopy(s['model_policy']['assigned'])]
    spent = 0
    if mutation == 'model': s['model_policy']['assigned']['model'] = 'unapproved'
    if mutation == 'fallback': s['model_policy']['allow_runtime_fallback'] = True
    if mutation == 'cap': s['budget']['max_cost_usd'] = None
    if mutation == 'spend': spent = .001
    with pytest.raises(AdapterError) as e:
        admit(s, ScopeCaps(0, 0), routes, roots=(tmp_path,), project_spend=spent)
    assert e.value.code == code


def test_scope_approval_is_enforced(tmp_path):
    s = spec(tmp_path); s['prompt'] = 'send an email'
    with pytest.raises(AdapterError) as e:
        admit(s, ScopeCaps(0, 0), [s['model_policy']['assigned']], roots=(tmp_path,))
    assert e.value.code == 'TOOL_DENIED'


@pytest.mark.parametrize('meter', [
    {'lifetime_usd': 0, 'limit_usd': 0},
    {'lifetime_usd': 0, 'remaining_usd': 0, 'state': 'stale'}, {},
])
def test_unknown_or_stale_account_refused(meter):
    with pytest.raises(ValueError): check_remaining(meter)


def test_zero_remaining_permits_verified_free_request_only():
    meter = {'lifetime_usd': 0, 'limit_usd': 0, 'remaining_usd': 0}
    assert check_remaining(meter, 0) == 0
    with pytest.raises(ValueError): check_remaining(meter, .00001)


def test_provider_ledger_is_exact_and_replay_deduplicated(sessions):
    receipt = {'response_id': 'provider-1', 'model': 'vendor/test', 'ts': 1,
               'usage': {'input_tokens': 10, 'output_tokens': 5},
               'cost_usd': .123456, 'cost_source': 'reported'}
    with sessions.begin() as db:
        put_provider_receipt(db, 'picoclaw', 'mcd-run-1', receipt)
        put_provider_receipt(db, 'picoclaw', 'mcd-run-1', receipt)
        rows = list(db.scalars(select(UsageRecord)))
        assert len(rows) == 1
        import json
        assert price(json.loads(rows[0].payload), config(db))[0] == receipt['cost_usd']


def test_cap_event_is_ui_visible(sessions, tmp_path):
    from tests.test_dispatcher import _settings, _registry, _card
    from dispatcher import Dispatcher
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    _card(sessions, tmp_path, 'print(1)')
    _, run_id = d._claim(1)[0]
    d._adapter_event(run_id, 'picoclaw', {'type': 'error', 'data': {'code': 'BUDGET_EXCEEDED'}})
    with sessions() as db:
        assert any(e.kind == 'cap_exceeded' for e in db.scalars(select(RunEvent)))


def test_provider_boundary_halts_future_requests_on_cap(monkeypatch):
    """Exercise real admission/accounting without requiring a loopback socket."""
    import json
    import time
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from integrations.zeroclaw import proxy as boundary
    from integrations.zeroclaw.admission import FreeModelCatalog
    from types import SimpleNamespace
    monkeypatch.setattr(boundary.http.server, 'ThreadingHTTPServer',
                        lambda *args: SimpleNamespace(daemon_threads=False, server_address=('127.0.0.1', 1)))
    catalog = FreeModelCatalog({'vendor/Exact:free': {'prompt': '0', 'completion': '0'}}, verified_at=int(time.time()))
    p = boundary.ProviderProxy(catalog, account_fetch=lambda key: {'lifetime_usd': 0, 'remaining_usd': 0})
    token = p.register('1', 'vendor/Exact:free', max_requests=1)
    run = p._by_run['1']
    payload = {'id': 'receipt-1', 'model': run.model,
               'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'cost': .0001}}
    assert p._account(run, 200, json.dumps(payload).encode())[0] == 502
    assert p.receipts('1')[0]['cost_usd'] == .0001
    assert 'cost_breach' in p.flags('1')
    assert p._handle('/v1/chat/completions', 'Bearer ' + token, b'{}')[0] == 403


def test_unavailable_account_blocks_before_provider_request(monkeypatch):
    import time
    from types import SimpleNamespace
    from integrations.zeroclaw import proxy as boundary
    from integrations.zeroclaw.admission import FreeModelCatalog
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic')
    monkeypatch.setattr(boundary.http.server, 'ThreadingHTTPServer',
                        lambda *args: SimpleNamespace(daemon_threads=False, server_address=('127.0.0.1', 1)))
    p = boundary.ProviderProxy(FreeModelCatalog({}, verified_at=int(time.time())), account_fetch=lambda key: {})
    with pytest.raises(boundary.Refusal) as exc:
        p.admit_account()
    assert exc.value.code == 'BUDGET_EXCEEDED'


def test_running_adapter_is_terminated_on_provider_cap(monkeypatch, tmp_path):
    import asyncio
    import time
    from types import SimpleNamespace
    from integrations.zeroclaw.adapter import ZeroClawAdapter
    adapter = object.__new__(ZeroClawAdapter)
    adapter.config = SimpleNamespace(tick_s=.001, proxy=SimpleNamespace(flags=lambda rid: {'cost_breach'}))
    adapter._run_dir = lambda rid: tmp_path
    adapter._drain = lambda *args: None
    stopped = []
    async def terminate(run): stopped.append(True)
    adapter._terminate = terminate
    adapter._finish = lambda run, status, code, message: run.update(status=status, error=code)
    class Process:
        returncode = None
        async def wait(self): await asyncio.sleep(10)
    run = {'spec': {'run_id': '1', 'limits': {'timeout_s': 30}},
           'clock': time.monotonic(), 'running_s': 0, 'status': 'running'}
    asyncio.run(adapter._supervise(run, Process()))
    assert stopped == [True]
    assert run['status'] == 'failed' and run['error'] == 'BUDGET_EXCEEDED'


def test_pi_runtime_binding_preserves_logical_assignment_and_model(tmp_path):
    from integrations.picoclaw.adapter import PicoClawAdapter, PicoClawConfig
    adapter = PicoClawAdapter(PicoClawConfig(tmp_path / 'state', assigned_agents=('codex',)))
    s = spec(tmp_path)
    s['model_policy']['assigned']['agent'] = 'codex'
    assert adapter._allowed_route(s)
    path = adapter._runtime_config({'spec': dict(s, run_id='config-probe')})
    import json
    assert json.loads(path.read_text())['model_list'][0]['model'] == 'vendor/Exact:free'
    assert s['model_policy']['assigned']['agent'] == 'codex'


def test_missing_scope_binding_blocks_dispatch_and_surfaces_event(sessions, tmp_path):
    import asyncio
    from tests.test_dispatcher import _settings, _registry, _card, _drain
    from tests.test_dispatcher_adapter_bridge import StubAdapter
    from dispatcher import Dispatcher
    from models import Run
    adapter = StubAdapter(); adapter.name = 'picoclaw'
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry(), adapters={'fake': adapter})
    _card(sessions, tmp_path, 'inspect', model='vendor/Exact:free', budget_usd=0)
    asyncio.run(_drain(d))
    assert adapter.specs == []
    with sessions() as db:
        run = db.scalar(select(Run))
        assert run.stage == 'failed'
        assert 'Approved scope caps' in run.error
        assert any(e.kind == 'cap_exceeded' for e in db.scalars(select(RunEvent)))


def test_provider_receipt_replaces_run_aggregate_in_billing(sessions):
    from models import Run
    from billing import dashboard
    receipt = {'response_id': 'response', 'model': 'vendor/test', 'ts': 100,
               'usage': {'input_tokens': 1, 'output_tokens': 1},
               'cost_usd': .1, 'cost_source': 'reported'}
    with sessions.begin() as db:
        run = Run(agent='codex', stage='failed', started_at=100, working_dir='/synthetic',
                  command='[]', log_path='', session_id='runtime-session', cost_usd=.1)
        db.add(run); db.flush()
        put_provider_receipt(db, 'codex', f'mcd-run-{run.id}', receipt)
        result = dashboard(db, period='24h', now=101)
        assert result['summary']['responses'] == 1
        assert result['summary']['api_equivalent_usd'] == .1


def test_live_receipts_update_budget_before_run_finishes(sessions, tmp_path):
    from tests.test_dispatcher import _settings, _registry, _card
    from dispatcher import Dispatcher
    from models import Run
    d = Dispatcher(sessions, _settings(tmp_path), registry=_registry())
    _card(sessions, tmp_path, 'inspect')
    _, rid = d._claim(1)[0]
    receipt = {'response_id': 'response-1', 'model': 'vendor/test', 'ts': 100,
               'usage': {'input_tokens': 1, 'output_tokens': 1}, 'cost_usd': .01}
    event = {'type': 'usage', 'data': {'provider_receipts': [receipt]}}
    d._adapter_event(rid, 'fake', event)
    d._adapter_event(rid, 'fake', event)
    with sessions() as db:
        assert db.get(Run, rid).stage == 'running'
        assert db.get(Run, rid).cost_usd == .01
