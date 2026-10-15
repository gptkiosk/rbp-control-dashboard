"""Agent settings are the user's. Installing, updating, rolling back or removing a managed agent tool, applying role guidance and
launching a run must leave every agent's own configuration, memory and credentials byte for byte as they were."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import dispatcher
import role_pack as rp
import tool_install as ti
from tests.test_tool_install import FakeOps, bump, catalog_dir, facts as linux_facts, run  # noqa: F401

NATIVE = {
    '.claude/settings.json': '{"model": "user-choice", "permissions": {"allow": ["Bash(ls)"]}}\n',
    '.claude/CLAUDE.md': 'My own Claude instructions.\n',
    '.claude/projects/p/memory.md': 'What Claude remembers.\n',
    '.codex/config.toml': 'model = "user-choice"\n[profiles.mine]\napproval = "never"\n',
    '.codex/AGENTS.md': 'My own Codex instructions.\n',
    '.codex/auth.json': '{"synthetic": "credential"}\n',
    '.hermes/config.yaml': 'model:\n  default: user/choice\nplatform_toolsets:\n  discord: [core]\n',
    '.hermes/.env': 'SYNTHETIC_KEY=synthetic-value\n',
    '.hermes/SOUL.md': 'My own Hermes soul.\n',
    '.hermes/memories/m.md': 'What Hermes remembers.\n',
    '.openclaw/openclaw.json': '{"agents": {"list": [{"id": "mine"}]}}\n',
    '.openclaw/agents/main/memory.md': 'What OpenClaw remembers.\n',
    '.grok/config.json': '{"model": "user-choice"}\n',
}


def snapshot(home: Path) -> dict:
    out = {}
    for path in sorted(home.rglob('*')):
        rel = str(path.relative_to(home))
        out[rel] = (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else ('dir', None)
    return out


PLATFORMS = {
    'linux-arm64': {},
    'darwin-arm64': dict(system='Darwin', machine='arm64', os_name='macOS', os_family='macos'),
}


@pytest.fixture(params=sorted(PLATFORMS))
def platform(request, catalog_dir):  # noqa: F811
    if request.param not in ti.load_catalog(catalog_dir).raw['requirements']['platforms']:
        pytest.skip(f'this product does not install tools on {request.param}')
    return request.param


@pytest.fixture
def cfg(tmp_path, catalog_dir, platform):  # noqa: F811
    home = tmp_path / 'home'
    home.mkdir()
    return ti.ToolsConfig(root=tmp_path / 'tools-root', catalog_dir=catalog_dir, platform_key=platform, home=home)


@pytest.fixture
def catalog(cfg):  # noqa: F811
    return ti.load_catalog(cfg.catalog_dir)


@pytest.fixture
def host(platform):
    return linux_facts(**PLATFORMS[platform])


@pytest.fixture
def user_home(cfg):  # noqa: F811
    for rel, text in NATIVE.items():
        path = cfg.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return cfg.home


def test_the_fixture_really_holds_every_agents_settings(user_home):
    assert {p.split('/')[0] for p in NATIVE} == {'.claude', '.codex', '.hermes', '.openclaw', '.grok'}
    assert len(snapshot(user_home)) >= len(NATIVE)


def test_the_snapshot_would_notice_a_changed_added_or_removed_setting(user_home):
    before = snapshot(user_home)
    target = user_home / '.codex/config.toml'
    target.write_text(NATIVE['.codex/config.toml'] + 'extra = 1\n')
    assert snapshot(user_home) != before
    target.write_text(NATIVE['.codex/config.toml'])
    (user_home / '.claude/new.json').write_text('{}')
    assert snapshot(user_home) != before
    (user_home / '.claude/new.json').unlink()
    (user_home / '.grok/config.json').unlink()
    assert snapshot(user_home) != before


@pytest.mark.parametrize('tool', ['claude-code', 'codex', 'openclaw'])
def test_updating_a_managed_npm_agent_tool_leaves_every_agents_settings_alone(cfg, catalog, user_home, host, tool):  # noqa: F811
    before = snapshot(user_home)
    run(cfg, catalog, tool, 'install', host=host)
    assert snapshot(user_home) == before
    first = ti.load_catalog(cfg.catalog_dir).raw['tools'][tool]['version']
    major, minor, patch = (first.split('-')[0].split('.') + ['0', '0'])[:3]
    bump(cfg, tool, f'{major}.{minor}.{int(patch) + 1}')
    catalog2 = ti.load_catalog(cfg.catalog_dir)
    run(cfg, catalog2, tool, 'update', host=host)
    assert snapshot(user_home) == before
    run(cfg, catalog2, tool, 'rollback', host=host)
    assert snapshot(user_home) == before
    run(cfg, catalog2, tool, 'remove', host=host)
    assert snapshot(user_home) == before, 'removing a managed tool must not remove or change anything the user owns'


@pytest.mark.parametrize('tool', ['hermes', 'grok'])
def test_installing_and_removing_hermes_or_grok_leaves_every_agents_settings_alone(cfg, catalog, user_home, host, tool):  # noqa: F811
    before = snapshot(user_home)
    run(cfg, catalog, tool, 'install', host=host)
    assert snapshot(user_home) == before
    run(cfg, catalog, tool, 'remove', host=host)
    assert snapshot(user_home) == before


def test_installers_never_run_with_the_users_real_home_as_home(cfg, catalog, user_home, host):  # noqa: F811
    for tool in ('claude-code', 'codex', 'openclaw', 'hermes', 'grok'):
        ops = FakeOps(catalog)
        run(cfg, catalog, tool, 'install', ops=ops, host=host)
        homes = {env.get('HOME') for env in ops.envs}
        assert str(user_home) not in homes, f'{tool}: an installer step ran with the real home as HOME'


def test_role_guidance_changes_only_its_marked_block_in_each_agents_instruction_file(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    work = tmp_path / 'work'
    work.mkdir()
    for rel, text in NATIVE.items():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(text)
    settings = SimpleNamespace(data_dir=tmp_path / 'data', product_short_name='MCD', workdir_roots=[work])
    monkeypatch.setattr(rp.RoleStore, 'available', lambda self: list(rp.REGISTRY))
    store = rp.RoleStore(settings, home=home)
    others = {rel: (home / rel).read_bytes() for rel in NATIVE if rel not in ('.hermes/SOUL.md',)}
    _, preview = store.preview({'hermes': 'delegator'})
    store.apply({'hermes': 'delegator'}, '', preview['plan_sha256'])
    soul = (home / '.hermes/SOUL.md').read_text()
    assert soul.startswith(NATIVE['.hermes/SOUL.md']) and soul.count(store.begin) == 1
    assert {rel: (home / rel).read_bytes() for rel in others} == others, 'role guidance touched a file it does not own'
    store.rollback()
    assert (home / '.hermes/SOUL.md').read_text() == NATIVE['.hermes/SOUL.md']


@pytest.mark.parametrize('name', ['HOME', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'HERMES_HOME', 'OPENCLAW_CONFIG_PATH', 'XDG_CONFIG_HOME', 'GROK_HOME'])
def test_agent_runs_keep_the_service_environment_that_points_at_the_users_settings(monkeypatch, name):
    monkeypatch.setenv(name, '/synthetic/user/location')
    monkeypatch.setenv('MAC_CONTROL_SECRET_SETTING', 'must-not-reach-the-agent')
    env = dispatcher.Dispatcher._env('hermes')
    assert env.get(name) == '/synthetic/user/location'
    assert 'MAC_CONTROL_SECRET_SETTING' not in env
