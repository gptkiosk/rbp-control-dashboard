"""OpenClaw targets also come from `openclaw agents list --json`, cached briefly, so agents its config file omits still count."""
import json
import subprocess
from types import SimpleNamespace

import native_routes


def test_cli_agents_are_merged_cached_and_forgotten(tmp_path, monkeypatch):
    cfg = tmp_path / 'openclaw.json'
    cfg.write_text(json.dumps({'agents': {'defaults': {'model': 'openrouter/free'}, 'list': [{'id': 'main'}]}}))
    settings = SimpleNamespace(environment='production', openclaw_config_path=cfg, hermes_config_path=tmp_path / 'none.yaml')
    from agents import AgentSpec
    monkeypatch.setattr(AgentSpec, 'available', lambda self, s: True)
    monkeypatch.setattr(AgentSpec, 'binary', lambda self, s: '/bin/openclaw')
    runs = []

    def fake(argv, **kw):
        runs.append(argv)
        return SimpleNamespace(returncode=0, stdout='[plugins] ready\n' + json.dumps([{'id': 'main'}, {'id': 'rcd-oc-developer', 'model': {'primary': 'vendor/m:free'}}, {'id': 'bad id!'}]))

    monkeypatch.setattr(subprocess, 'run', fake)
    native_routes.forget()
    targets = {t['id']: t for t in native_routes.read(settings, wait=True)['openclaw']['targets']}
    assert set(targets) == {'main', 'rcd-oc-developer'} and targets['rcd-oc-developer']['model'] == 'vendor/m:free'
    native_routes.read(settings)
    assert len(runs) == 1  # cached
    native_routes.forget(); native_routes.read(settings, wait=True)
    assert len(runs) == 2


def test_a_failing_cli_leaves_the_config_targets(tmp_path, monkeypatch):
    cfg = tmp_path / 'openclaw.json'
    cfg.write_text(json.dumps({'agents': {'defaults': {'model': 'openrouter/free'}, 'list': [{'id': 'main'}]}}))
    settings = SimpleNamespace(environment='production', openclaw_config_path=cfg, hermes_config_path=tmp_path / 'none.yaml')
    from agents import AgentSpec
    monkeypatch.setattr(AgentSpec, 'available', lambda self, s: True)
    monkeypatch.setattr(AgentSpec, 'binary', lambda self, s: '/bin/openclaw-broken')
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kw: SimpleNamespace(returncode=1, stdout='boom'))
    native_routes.forget()
    assert [t['id'] for t in native_routes.read(settings, wait=True)['openclaw']['targets']] == ['main']


def test_a_page_read_never_waits_for_the_cli(tmp_path, monkeypatch):
    import time as _time
    cfg = tmp_path / 'openclaw.json'
    cfg.write_text(json.dumps({'agents': {'defaults': {'model': 'openrouter/free'}, 'list': [{'id': 'main'}]}}))
    settings = SimpleNamespace(environment='production', openclaw_config_path=cfg, hermes_config_path=tmp_path / 'none.yaml')
    from agents import AgentSpec
    monkeypatch.setattr(AgentSpec, 'available', lambda self, s: True)
    monkeypatch.setattr(AgentSpec, 'binary', lambda self, s: '/bin/openclaw-slow')
    def slow(argv, **kw):
        _time.sleep(1.5)
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'id': 'rcd-oc-developer'}]))
    monkeypatch.setattr(subprocess, 'run', slow)
    native_routes._cli.update(at=0.0, key=None, agents=[], loaded=False, refreshing=False)
    started = _time.monotonic()
    first = [t['id'] for t in native_routes.read(settings)['openclaw']['targets']]
    assert _time.monotonic() - started < 0.5 and first == ['main']        # the file's agents at once; the CLI runs in the background
    deadline = _time.monotonic() + 5
    while native_routes._cli['refreshing'] and _time.monotonic() < deadline:
        _time.sleep(0.05)
    assert 'rcd-oc-developer' in [t['id'] for t in native_routes.read(settings)['openclaw']['targets']]
