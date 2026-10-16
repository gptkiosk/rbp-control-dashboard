"""What an update must leave alone: the user's own coordinator wording and their saved preferences, across versions."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import profiles
import role_pack as rp


@pytest.fixture
def store(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    settings = SimpleNamespace(data_dir=tmp_path / 'data', product_short_name='MCD', workdir_roots=[tmp_path])
    monkeypatch.setattr(rp.RoleStore, 'available', lambda self: list(rp.REGISTRY))
    return rp.RoleStore(settings, home=home)


def custom(store, name, text):
    path = store.folder / 'custom' / name
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text)
    return path


# ------------------------------------------------------------------------ role pack overrides
def test_without_a_copy_the_shipped_text_is_used_and_nothing_is_reported_as_customized(store):
    assert store.source('plan.txt') == (store.pack / 'plan.txt').read_text()
    assert store.customized() == {'custom': [], 'custom_ignored': {}}


def test_a_users_copy_replaces_the_shipped_text_and_survives_the_shipped_file_changing(store, tmp_path):
    shipped = (store.pack / 'plan.txt').read_text()
    mine = shipped.replace('Read-only project planning.', 'Read-only planning, my way.')
    custom(store, 'plan.txt', mine)
    assert store.source('plan.txt') == mine and 'my way' in store.source('plan.txt')
    assert store.customized()['custom'] == ['plan.txt']
    # An update replaces the shipped file; the copy in the data folder is untouched and still wins.
    pack = tmp_path / 'newer-pack'
    pack.mkdir()
    for p in store.pack.iterdir():
        (pack / p.name).write_text(p.read_text() + ('\nA new shipped sentence.\n' if p.name == 'plan.txt' else ''))
    upgraded = rp.RoleStore(store.settings, home=store.home, pack_dir=pack)
    assert upgraded.source('plan.txt') == mine and 'A new shipped sentence' not in upgraded.source('plan.txt')
    assert 'A new shipped sentence' in upgraded.source('review.txt') + (pack / 'plan.txt').read_text()


@pytest.mark.parametrize('edit,why', [
    (lambda t: t.replace('$schema', ''), 'missing $schema'),
    (lambda t: t.replace('$standards', ''), 'missing $standards'),
    (lambda t: t + '\nThat costs $5 a month.', ''),              # a stray $ would break substitution
    (lambda t: '   \n', 'empty'),
])
def test_a_broken_copy_is_ignored_so_a_bad_edit_never_stops_planning(store, edit, why):
    shipped = (store.pack / 'plan.txt').read_text()
    custom(store, 'plan.txt', edit(shipped))
    assert store.source('plan.txt') == shipped
    ignored = store.customized()['custom_ignored']
    assert 'plan.txt' in ignored and why in ignored['plan.txt']


def test_a_symlinked_copy_is_refused(store, tmp_path):
    real = tmp_path / 'elsewhere.txt'
    real.write_text((store.pack / 'plan.txt').read_text())
    path = store.folder / 'custom' / 'plan.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(real)
    assert store.source('plan.txt') == (store.pack / 'plan.txt').read_text()
    assert 'plan.txt' in store.customized()['custom_ignored']


def test_a_custom_soul_or_context_goes_into_the_guidance_but_still_cannot_carry_secrets_or_host_paths(store):
    custom(store, 'context.md', 'My own coordination rules.\n')
    assert 'My own coordination rules.' in store.guidance()
    custom(store, 'context.md', 'Keep notes in /Users/me/private.\n')
    with pytest.raises(rp.RoleError):
        store.guidance()


def test_status_lists_the_customized_files(store):
    custom(store, 'review.txt', (store.pack / 'review.txt').read_text() + '\nExtra review rule.\n')
    status = store.status()
    assert status['custom'] == ['review.txt'] and status['custom_ignored'] == {}


def test_the_planner_prompt_uses_the_users_copy(store, monkeypatch):
    import projects
    monkeypatch.setattr(projects, 'RoleStore', lambda settings: store)
    custom(store, 'plan.txt', (store.pack / 'plan.txt').read_text().replace('Read-only project planning.', 'MY PLANNING RULES.'))
    text = projects.role_prompt('plan', schema='{}', catalog='[]', project='p', standards='s')
    assert text.startswith('MY PLANNING RULES.')


# ------------------------------------------------------------------------- saved preferences
def test_preferences_saved_by_a_newer_version_still_load_in_an_older_one():
    saved = json.loads(profiles.Preferences().model_dump_json())
    saved['a_preference_from_the_future'] = True
    saved['github']['another_future_key'] = 1
    saved['theme'] = 'dark'
    loaded = profiles.Preferences.stored(json.dumps(saved))
    assert loaded.theme == 'dark' and not hasattr(loaded, 'a_preference_from_the_future')


def test_preferences_saved_by_an_older_version_get_defaults_for_what_is_new():
    old = {'theme': 'light', 'ai_agent': 'claude'}        # a profile written before most preferences existed
    loaded = profiles.Preferences.stored(json.dumps(old))
    assert loaded.theme == 'light' and loaded.ai_agent == 'claude'
    assert loaded.use_saved_openrouter_key is False and loaded.allow_discord_maintenance is False and loaded.allow_discord_control is False


def test_editing_still_rejects_unknown_keys():
    with pytest.raises(ValueError):
        profiles.Preferences.model_validate({'theme': 'dark', 'surprise': 1})


def test_the_coordinator_wording_has_a_version_label_and_a_hash_that_follow_what_is_in_effect(store):
    shipped = store.version()
    assert shipped['shipped'] == '3' and shipped['label'] == 'v3' and shipped['custom'] == [] and len(shipped['sha']) == 12
    custom(store, 'plan.txt', (store.pack / 'plan.txt').read_text().replace('Read-only project planning.', 'MY WORDING.'))
    mine = store.version()
    assert mine['label'] == 'v3+custom' and mine['custom'] == ['plan.txt'] and mine['sha'] != shipped['sha']
    assert 'VERSION' not in store.customized()['custom'] and 'VERSION' not in store.customized()['custom_ignored']
