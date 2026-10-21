"""Pause the projects in progress for a dashboard update and resume exactly those afterwards."""
import pytest

import projects
from settings import get_settings
from tests.test_auth import begin, complete, secured  # noqa: F401
from tests.test_profiles import signed


@pytest.fixture
def env(tmp_path, secured):  # noqa: F811
    signed(secured)
    return secured, get_settings(), tmp_path / 'ws' / 'proj'


def make(s, settings, workspace, title, state):
    p = projects.create(s, dict(title=title, brief='B', working_dir=str(workspace)), settings, 'operator')
    p.state = state
    return p


def test_pause_for_the_update_then_resume_only_those(env):
    c, settings, workspace = env
    with c.app.state.sessions() as s:
        a = make(s, settings, workspace, 'Doors', 'active'); b = make(s, settings, workspace, 'Other', 'active')
        make(s, settings, workspace, 'Done', 'complete'); s.commit(); a_id, b_id = a.id, b.id
    listed = c.get('/api/app-updates/projects').json()
    assert [p['title'] for p in listed['in_progress']] == ['Doors', 'Other'] and listed['paused_for_update'] == []
    assert c.post('/api/app-updates/pause-projects', json={}).status_code == 422          # needs confirmation
    paused = c.post('/api/app-updates/pause-projects', json={'confirm': True}).json()
    assert [p['id'] for p in paused['paused']] == [a_id, b_id] and paused['in_progress'] == []
    # The operator resumes one by hand in the meantime; the resume offer then leaves it alone.
    with c.app.state.sessions() as s:
        projects.get(s, b_id).state = 'active'; s.commit()
    assert [p['id'] for p in c.get('/api/app-updates/projects').json()['paused_for_update']] == [a_id]
    resumed = c.post('/api/app-updates/resume-projects', json={'confirm': True}).json()
    assert [p['id'] for p in resumed['resumed']] == [a_id]
    assert c.get('/api/app-updates/projects').json()['paused_for_update'] == []
    with c.app.state.sessions() as s:
        assert projects.get(s, a_id).state == 'active'
