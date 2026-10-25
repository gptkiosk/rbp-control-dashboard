from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcd_server  # noqa: E402


class FakeApi:
    def __init__(self):
        self.calls = []
        self.cards = {}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path == "/api/cards":
            card = {"id": len(self.cards) + 1, "title": body["title"], "column": "backlog",
                    "assignee_type": body["assignee_type"], "agent": body.get("agent"),
                    "tags": body["tags"], "depends_on": body["depends_on"], "blocked_by": [],
                    "needs_approval": "push" in body["body"], "approval_reasons": ["prompt pushes or merges code"]
                    if "push" in body["body"] else []}
            self.cards[card["id"]] = card
            return card
        if method == "PATCH":
            cid = int(path.rsplit("/", 1)[1])
            card = self.cards[cid]
            if body.get("column") == "queued":
                card["column"] = "review" if card["needs_approval"] else "queued"
            return card
        if method == "GET" and path == "/api/cards":
            return {"cards": list(self.cards.values())}
        raise AssertionError((method, path))


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(mcd_server, "request", fake)
    return fake


def test_human_task_needs_no_working_dir(api):
    out = mcd_server.create_task("Sign the vendor contract", "human", acceptance="Signed PDF in Drive",
                                 tags=["Admin"], depends_on=[])
    sent = api.calls[0][2]
    assert sent["assignee_type"] == "human" and "agent" not in sent and sent["acceptance"] == "Signed PDF in Drive"
    assert out["assignee"] == "human"


def test_agent_task_requires_working_dir(api):
    with pytest.raises(mcd_server.McdError):
        mcd_server.create_task("Fix tests", "claude")


def test_queue_and_status_changes_refused_before_partial_writes(api):
    with pytest.raises(mcd_server.McdError):
        mcd_server.create_task("Ship it", "codex", description="then git push", working_dir="/w", queue=True)
    with pytest.raises(mcd_server.McdError):mcd_server.update_task(1,status='done',title='Done')
    assert api.calls==[]


def test_list_filters(api):
    mcd_server.create_task("A", "human", tags=["ops"])
    mcd_server.create_task("B", "claude", working_dir="/w")
    assert [t["title"] for t in mcd_server.list_tasks(assignee="human")] == ["A"]
    assert [t["title"] for t in mcd_server.list_tasks(tag="OPS")] == ["A"]


def test_update_requires_a_change(api):
    with pytest.raises(mcd_server.McdError):
        mcd_server.update_task(1)


def test_private_credential_read_and_symlink_permissions_refusal(tmp_path,monkeypatch):
    path=tmp_path/'token';path.write_text('a'*64+'\n');path.chmod(0o600)
    monkeypatch.setattr(mcd_server,'TOKEN_PATH',path)
    assert mcd_server.credential()=='a'*64
    path.chmod(0o644)
    with pytest.raises(mcd_server.McdError):mcd_server.credential()
    path.chmod(0o600);link=tmp_path/'link';link.symlink_to(path)
    monkeypatch.setattr(mcd_server,'TOKEN_PATH',link)
    with pytest.raises(mcd_server.McdError):mcd_server.credential()


@pytest.mark.parametrize('url',['https://example.com','http://localhost:8800','http://127.0.0.1:8800/evil','http://127.0.0.1:8800?secret=x','http://user:secret@127.0.0.1:8800','http://127.0.0.1:notaport'])
def test_credential_cannot_be_sent_to_remote_ambiguous_or_malformed_address(monkeypatch,url):
    monkeypatch.setattr(mcd_server,'BASE_URL',url)
    monkeypatch.setattr(mcd_server,'credential',lambda:pytest.fail('Credential read before URL validation'))
    with pytest.raises(mcd_server.McdError):mcd_server.request('GET','/api/cards')


def test_transport_uses_curated_api_no_proxies_and_no_redirects(tmp_path,monkeypatch):
    path=tmp_path/'token';path.write_text('b'*64+'\n');path.chmod(0o600)
    monkeypatch.setattr(mcd_server,'TOKEN_PATH',path)
    recorded={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{"cards":[]}'
    class Opener:
        def open(self,req,timeout):recorded['url']=req.full_url;recorded['headers']=dict(req.header_items());return Response()
    def builder(*handlers):
        assert handlers[0].proxies=={} and isinstance(handlers[1],mcd_server.NoRedirect)
        assert handlers[1].redirect_request(None,None,None,None,None,None) is None
        return Opener()
    monkeypatch.setattr(mcd_server.urllib.request,'build_opener',builder)
    assert mcd_server.request('GET','/api/cards')=={'cards':[]}
    assert recorded['url']=='http://127.0.0.1:8800/api/agent-tools/tasks'
    assert recorded['headers']['Authorization']=='Bearer '+'b'*64


def test_coordinator_tool_requests_only_selected_context(api):
    api.cards={}
    calls=[]
    original=__import__('mcd_server').request
    try:
        __import__('mcd_server').request=lambda method,path,body=None: calls.append((method,path,body)) or {'context_manifest':{}}
        __import__('mcd_server').coordinator_read('context',working_dir='/project root',project_type='local-website')
    finally:
        __import__('mcd_server').request=original
    assert calls==[('GET','/api/coordinator?operation=context&working_dir=%2Fproject+root&project_type=local-website',None)]
