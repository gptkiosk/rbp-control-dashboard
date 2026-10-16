import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from alerts import AlertMonitor, HermesSender, load_rules, run_message
from models import AlertEvent, Run, ServiceSnapshot
from tests.test_dispatcher import _card, _drain, _settings, _registry
from dispatcher import Dispatcher

TARGET = "discord:123456789012345678"

def config(path, delivery=True, **values):
    text = f'enabled = true\ndelivery_enabled = {str(delivery).lower()}\ndestination = "{values.get("destination", TARGET)}"\n'
    path.write_text(text)
    path.chmod(0o600)

def monitor(sessions, tmp_path, now, sender=None, delivery=True):
    path = tmp_path / 'alerts.toml'; config(path, delivery)
    sent = []
    def send(target, message):
        sent.append((target, message))
        return '1525000000000000000'
    m = AlertMonitor(sessions, path, sender or send, clock=lambda: now[0])
    return m, sent

def run(sessions, now, stage='failed', ended=None, **extra):
    with sessions.begin() as s:
        r=Run(agent='codex', stage=stage, started_at=now-10, ended_at=ended if ended is not None else now,
              working_dir='/private/path', command='private prompt', log_path='', exit_code=7, error='private token', **extra)
        s.add(r); s.flush(); return r.id

def snapshots(sessions, times, counts, **extra):
    with sessions.begin() as s:
        for t,count in zip(times, counts):
            s.add(ServiceSnapshot(ts=t,label='com.operator.test',domain='gui',runs=count,state='running',last_exit='1', **extra))

def test_historical_failures_ignored_new_failures_once_across_restarts(sessions, tmp_path):
    now=[1000]
    run(sessions, 999); run(sessions, 1000)
    m,sent=monitor(sessions,tmp_path,now)
    m.tick(); assert not sent
    now[0]=1001; run_id=run(sessions,1001)
    m.tick(); m.tick()
    assert len(sent)==1 and sent[0][0]==TARGET and f'#{run_id}' in sent[0][1]
    assert all(secret not in sent[0][1] for secret in ('private','token','path','prompt'))
    again=AlertMonitor(sessions,m.path,m.sender,clock=lambda:now[0]); again.tick()
    assert len(sent)==1

def test_forced_dispatcher_failure_creates_one_notification(sessions,tmp_path):
    import time
    now=[int(time.time())]
    m,sent=monitor(sessions,tmp_path,now); m.tick()
    cid=_card(sessions,tmp_path,"import sys;sys.exit(23)")
    d=Dispatcher(sessions,_settings(tmp_path),registry=_registry())
    asyncio.run(_drain(d))
    now[0]=int(time.time())+2   # the monitor's clock must be past the run's real end time, whatever the second boundary
    m.tick(); m.tick()
    assert len(sent)==1 and 'Exit: 23' in sent[0][1]

def test_cancelled_and_successful_not_alerted_but_timeout_is(sessions,tmp_path):
    now=[1000]; m,sent=monitor(sessions,tmp_path,now); m.tick()
    now[0]=1001
    for stage in ('cancelled','succeeded','timeout'): run(sessions,1001,stage)
    m.tick()
    assert len(sent)==1 and 'timeout' in sent[0][1]

def test_uncertain_delivery_and_restart_claim_never_auto_retry(sessions,tmp_path):
    now=[1000]; calls=[]
    def unknown(*args): calls.append(args); return None
    m,_=monitor(sessions,tmp_path,now,sender=unknown); m.tick()
    now[0]=1001; run(sessions,1001)
    m.tick(); m.tick()
    assert len(calls)==1 and m.status()['attention']==1
    with sessions.begin() as s:
        event=s.scalar(select(AlertEvent)); event.status='delivering'
    async def restart():
        m.start(); await m.stop()
    asyncio.run(restart())
    m.tick(); assert len(calls)==1
    assert m.status()['events'][0]['status']=='uncertain'

def test_pause_invalid_rules_changed_destination_and_expiry(sessions,tmp_path):
    now=[1000]; m,sent=monitor(sessions,tmp_path,now,delivery=False); m.tick()
    now[0]=1001; run(sessions,1001); m.tick()
    assert not sent and m.status()['pending']==1
    m.path.write_text('enabled = true\ndelivery_enabled = true\ndestination = "discord:#unapproved"')
    m.tick(); assert m.status()['error'] and not sent
    config(m.path,destination='discord:1111111111111111111'); m.tick()
    assert m.status()['events'][0]['status']=='held' and not sent
    now[0]=1002; run(sessions,1002); config(m.path,delivery=False); m.tick()
    now[0]=5003; config(m.path); m.tick()
    assert not sent and any(e['status']=='expired' for e in m.status()['events'])

def test_crash_loop_one_event_until_recovery_and_schedules_are_allowed(sessions,tmp_path):
    now=[1000]; m,sent=monitor(sessions,tmp_path,now); m.tick()
    snapshots(sessions,[1001,1061],[1,8])
    now[0]=1061; m.tick(); m.tick()
    assert len(sent)==1 and 'Service crash loop' in sent[0][1]
    snapshots(sessions,[1121],[15]); now[0]=1121; m.tick(); assert len(sent)==1
    # When the rolling burst leaves the window, two distinct healthy samples close it.
    snapshots(sessions,[1701,1761,1821],[15,15,15]); now[0]=1761; m.tick(); now[0]=1821; m.tick()
    snapshots(sessions,[1881],[23]); now[0]=1881; m.tick(); assert len(sent)==2

@pytest.mark.parametrize('extra,counts', [({'run_interval_s':60},list(range(1,11))),({'calendar':True},[1,15]),({},[200,1,2])])
def test_expected_schedules_and_counter_reset_not_crashes(sessions,tmp_path,extra,counts):
    now=[1000]; m,sent=monitor(sessions,tmp_path,now); m.tick()
    times=[1001+i*60 for i in range(len(counts))]
    snapshots(sessions,times,counts,**extra); now[0]=times[-1]; m.tick()
    assert not sent

def test_stale_samples_and_single_sample_not_crashes(sessions,tmp_path):
    now=[1000]; m,sent=monitor(sessions,tmp_path,now); m.tick()
    snapshots(sessions,[1001,1061],[1,100]); now[0]=1500; m.tick(); assert not sent

def test_rules_permissions_symlink_and_message_directives(tmp_path):
    path=tmp_path/'alerts.toml'; config(path)
    path.chmod(0o666); assert load_rules(path)[1]
    path.chmod(0o600)
    alias=tmp_path/'alias'; alias.symlink_to(path); assert load_rules(alias)[1]
    r=SimpleNamespace(id=1,agent='@everyone MEDIA:/secret',stage='failed',exit_code=1)
    message=run_message(r)
    assert '@' not in message and 'MEDIA:' not in message and '/secret' not in message

def test_hermes_transport_uses_stdin_and_requires_matching_ack(monkeypatch):
    import alerts
    calls=[]
    class Process:
        returncode=0
        def __init__(self,argv,**options): calls.append((argv,options))
        def communicate(self,message,timeout):
            calls.append(message)
            return json.dumps({'success':True,'platform':'discord','chat_id':TARGET.split(':')[1],'message_id':'1525000000000000000'}),'private stderr'
    monkeypatch.setattr(alerts.subprocess,'Popen',Process)
    assert HermesSender('/bin/hermes')(TARGET,'safe message')=='1525000000000000000'
    assert calls[0][0]==['/bin/hermes','send','--to',TARGET,'--file','-','--json']
    assert 'safe message' not in calls[0][0] and calls[1]=='safe message'
    assert not calls[0][1].get('shell')

def test_alert_api_and_acknowledgement_do_not_send(make_client):
    with make_client() as client:
        assert client.get('/api/alerts').json()['enabled'] is False
        with client.app.state.sessions.begin() as s:
            s.add(AlertEvent(id='a'*32,source_key='test',kind='run_failed',message='safe',destination=TARGET,status='uncertain',created_at=1000))
        assert client.get('/api/alerts').json()['attention']==1
        assert client.post('/api/alerts/'+'a'*32+'/acknowledge').json()['ok']
        assert client.get('/api/alerts').json()['attention']==0
        assert client.get('/api/alerts').json()['events'][0]['status']=='uncertain'


def test_run_already_running_at_activation_is_not_lost(sessions,tmp_path):
    with sessions.begin() as s:
        r=Run(agent='codex',stage='running',started_at=900,ended_at=None,working_dir='/w',command='[]',log_path='')
        s.add(r); s.flush(); run_id=r.id
    now=[1000]; m,sent=monitor(sessions,tmp_path,now); m.tick()
    with sessions.begin() as s:
        r=s.get(Run,run_id); r.stage='failed'; r.ended_at=1000; r.exit_code=1
    m.tick(); assert len(sent)==1


def test_a_project_whose_plan_failed_validation_is_alerted_once_even_though_its_run_succeeded(sessions,tmp_path):
    """The planner run succeeds, then the plan is refused (a dependency or missing field): no failed run exists, so the project state is the signal."""
    from models import Project
    now=[1000]
    m,sent=monitor(sessions,tmp_path,now); m.tick()
    with sessions.begin() as s:
        s.add(Project(id=5,state='planning_failed',revision=1,error='Dependencies must connect different stories in this project.',
                      created_by='owner',created_at=900,updated_at=999,document='{"title": "Site"}'))
    m.tick(); assert not sent                                                       # stopped before the monitor was active: history, not news
    now[0]=1001
    with sessions.begin() as s:
        p=s.get(Project,5); p.error='Story "S1" (s1) needs instructions.'; p.updated_at=1001
    m.tick(); m.tick()
    assert len(sent)==1 and 'project #5' in sent[0][1] and 'needs instructions' in sent[0][1] and sent[0][0]==TARGET
    now[0]=1002
    with sessions.begin() as s:
        p=s.get(Project,5); p.error='Dependencies must connect different stories in this project.'; p.updated_at=1002   # a different failure is news again
    m.tick(); assert len(sent)==2 and 'Dependencies must connect' in sent[1][1]
