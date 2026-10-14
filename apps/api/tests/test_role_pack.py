from pathlib import Path
from types import SimpleNamespace
import pytest
import role_pack as rp

@pytest.fixture
def store(tmp_path, monkeypatch):
    home = tmp_path / 'home'; home.mkdir()
    workspace = tmp_path / 'workspace'; workspace.mkdir()
    settings = SimpleNamespace(data_dir=tmp_path/'data', product_short_name='MCD', workdir_roots=[workspace])
    monkeypatch.setattr(rp.RoleStore, 'available', lambda self: list(rp.REGISTRY))
    return rp.RoleStore(settings, home=home)

@pytest.mark.parametrize('agent', list(rp.REGISTRY))
def test_each_agent_can_receive_managed_guidance_and_rollback(store, agent):
    workspace = str(store.settings.workdir_roots[0])
    paths = store.target_paths(agent, workspace)
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text('Operator instructions\n')
    plan, preview = store.preview({agent:'delegator'}, workspace)
    assert all('Operator instructions' not in row['diff'] for row in preview['changes'])
    store.apply({agent:'delegator'}, workspace, preview['plan_sha256'])
    assert store.delegator() == agent
    for p in paths:
        assert p.read_text().startswith('Operator instructions\n')
        assert p.read_text().count(store.begin) == 1
    store.rollback()
    assert all(p.read_text() == 'Operator instructions\n' for p in paths)


def test_assignment_demotes_previous_delegator_without_overwriting_notes(store):
    _, preview = store.preview({'hermes':'delegator'})
    store.apply({'hermes':'delegator'}, '', preview['plan_sha256'])
    _, preview = store.preview({'hermes':'worker','codex':'delegator'})
    store.apply({'hermes':'worker','codex':'delegator'}, '', preview['plan_sha256'])
    assert store.begin not in (store.home/'.hermes/SOUL.md').read_text()
    assert store.delegator() == 'codex'
    store.rollback()
    assert store.delegator() == 'hermes'


def test_stale_preview_and_rollback_preserve_new_operator_edits(store):
    p = store.home / '.codex/AGENTS.md'; p.parent.mkdir(); p.write_text('old')
    _, preview = store.preview({'codex':'delegator'})
    p.write_text('new')
    with pytest.raises(rp.RoleError, match='changed'):
        store.apply({'codex':'delegator'}, '', preview['plan_sha256'])
    _, preview = store.preview({'codex':'delegator'})
    store.apply({'codex':'delegator'}, '', preview['plan_sha256'])
    p.write_text(p.read_text()+'operator edit')
    with pytest.raises(rp.RoleError, match='changed'):
        store.rollback()
    assert p.read_text().endswith('operator edit')


def test_refuses_duplicate_delegators_uninstalled_agents_and_symlink_targets(store, monkeypatch):
    with pytest.raises(rp.RoleError, match='at most one'):
        store.preview({'codex':'delegator','claude':'delegator'})
    monkeypatch.setattr(store, 'available', lambda: [])
    with pytest.raises(rp.RoleError, match='Install'):
        store.preview({'codex':'delegator'})
    monkeypatch.setattr(store, 'available', lambda: ['codex'])
    (store.home/'.codex').symlink_to(store.settings.workdir_roots[0], target_is_directory=True)
    with pytest.raises(rp.RoleError, match='symlink'):
        store.preview({'codex':'delegator'})


def test_pack_lint_refuses_private_host_paths(store):
    pack = store.folder / 'bad-pack'; pack.mkdir(parents=True)
    (pack/'SOUL.md').write_text('/Users/operator/private')
    (pack/'context.md').write_text('generic')
    store.pack = pack
    with pytest.raises(rp.RoleError, match='private host'):
        store.preview({'hermes':'delegator'})


def test_interrupted_assignment_recovers_only_its_own_changes(store, monkeypatch):
    original = rp._write
    def crash(path, text):
        if path == store.state:
            raise SystemExit('synthetic crash')
        original(path, text)
    _, preview = store.preview({'codex':'delegator'})
    monkeypatch.setattr(rp, '_write', crash)
    with pytest.raises(SystemExit):
        store.apply({'codex':'delegator'}, '', preview['plan_sha256'])
    assert store.status()['recovery_required']
    monkeypatch.setattr(rp, '_write', original)
    store.recover()
    assert not store.pending.exists()
    assert not (store.home/'.codex/AGENTS.md').exists()
    assert store.delegator() == 'hermes'


def test_interrupted_assignment_refuses_to_erase_operator_edits(store, monkeypatch):
    original = rp._write
    def crash(path, text):
        if path == store.state:
            raise SystemExit('synthetic crash')
        original(path, text)
    _, preview = store.preview({'codex':'delegator'})
    monkeypatch.setattr(rp, '_write', crash)
    with pytest.raises(SystemExit):
        store.apply({'codex':'delegator'}, '', preview['plan_sha256'])
    monkeypatch.setattr(rp, '_write', original)
    target = store.home/'.codex/AGENTS.md';target.write_text(target.read_text()+'new operator text')
    with pytest.raises(rp.RoleError, match='preserved'):
        store.recover()
    assert target.read_text().endswith('new operator text')
