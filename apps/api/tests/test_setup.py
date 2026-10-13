"""Setup progress is operator-owned, bounded and cannot change runtime policy."""
import json
from models import UserProfile
from tests.test_profiles import OWNER, signed
from tests.test_auth import secured, begin, complete

def test_setup_progress_persists_without_overwriting_preferences(secured):
    signed(secured)
    # Old profiles receive safe defaults without a database migration.
    with secured.app.state.sessions.begin() as s:
        s.add(UserProfile(owner=OWNER, preferences=json.dumps({'theme':'dark','planning_bias':73})))
    p=secured.get('/api/profile').json()
    assert p['preferences']['setup']=={'step':0,'status':'new','confirmed':[]}
    state={'step':3,'status':'in_progress','confirmed':['host','native_routes']}
    r=secured.patch('/api/profile/setup',json=state)
    assert r.status_code==200,r.text
    p=secured.get('/api/profile').json()['preferences']
    assert p['setup']==state and p['theme']=='dark' and p['planning_bias']==73
    assert p['allow_discord_planning'] is False
    assert secured.patch('/api/profile/setup',json={**state,'status':'complete'}).status_code==200
    assert secured.get('/api/profile').json()['preferences']['setup']['status']=='complete'

def test_setup_progress_isolated_between_users(secured):
    signed(secured)
    secured.patch('/api/profile/setup',json={'step':5,'status':'complete','confirmed':['tour']})
    secured.post('/auth/logout')
    assert complete(secured,begin(secured),email='reviewer@example.com',sub='subject2').status_code==303
    assert secured.get('/api/profile').json()['preferences']['setup']['status']=='new'

def test_setup_requires_operator_and_validates_bounded_state(secured):
    assert secured.patch('/api/profile/setup',json={'step':0}).status_code==401
    signed(secured)
    for body in [{'step':6},{'step':-1},{'step':'3'},{'status':'approved'},{'confirmed':['credential']},{'key':'private-key'}]:
        assert secured.patch('/api/profile/setup',json=body).status_code==422
    assert secured.get('/api/profile').json()['preferences']['setup']['status']=='new'
