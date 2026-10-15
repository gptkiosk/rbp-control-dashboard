"""Additions to a repository's standards: only additions, only by approval, only on a new branch, never pushed."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import standards as st
import standards_proposals as sp
from models import Project, StandardsProposal
from tests.test_auth import secured  # noqa: F401
from tests.test_profiles import call, paired, pref, signed
from tests.test_standards import SAMPLE

FILE = 'docs/development/standards.md'


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    (root / 'docs/development').mkdir(parents=True)
    (root / FILE).write_text(SAMPLE)
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'start')
    git(root, 'config', 'user.name', 'Test')
    git(root, 'config', 'user.email', 'test@example.com')
    git(root, 'config', 'commit.gpgsign', 'false')
    return root


RISK = {'area': 'Email sending', 'examples': 'newsletters, reset mail', 'default_risk': 'high', 'route': 'foundation', 'extra': 'new kinds need a plan row'}


# ------------------------------------------------------------------------------- composing an addition
def test_a_risk_row_is_added_to_the_end_of_the_table_and_nothing_else_changes():
    new = st.compose_addition(SAMPLE, 'risk', [RISK])
    assert st.additive_problems(SAMPLE, new) == []
    assert '| Email sending | newsletters, reset mail | high | foundation | new kinds need a plan row |' in new
    area = next(a for a in st._parse(new, 'x', {})['areas'] if a['slug'] == 'email-sending')
    assert area['risk'] == 'high'
    assert [l for l in new.split('\n') if l not in SAMPLE.split('\n')] == ['| Email sending | newsletters, reset mail | high | foundation | new kinds need a plan row |']


def test_a_check_is_added_to_the_definition_of_done():
    new = st.compose_addition(SAMPLE, 'checks', [{'touches': 'a migration', 'run': 'alembic upgrade head on a copy', 'notes': 'additive only'}])
    assert st.additive_problems(SAMPLE, new) == []
    assert any(c['touches'] == 'a migration' for c in st._parse(new, 'x', {})['checks'])


def test_security_bullets_go_under_the_security_section_or_start_one():
    with_section = SAMPLE + '\n## Security checks for high-risk stories\n\n- No secrets in code.\n\n## Later\n\ntext\n'
    new = st.compose_addition(with_section, 'security', [{'text': 'Webhook handlers verify the signature first.'}])
    lines = new.split('\n')
    assert lines.index('- Webhook handlers verify the signature first.') == lines.index('- No secrets in code.') + 1
    assert st.additive_problems(with_section, new) == []
    fresh = st.compose_addition(SAMPLE, 'security', [{'text': 'Check it.'}])
    assert '## Security checks for high-risk stories' in fresh and fresh.rstrip().endswith('- Check it.')


def test_only_tightening_rules_can_be_added():
    assert st.compose_addition(SAMPLE, 'rules', [{'rule': 'unknown areas', 'value': 'refused'}]).rstrip().endswith('- unknown areas: refused')
    for rule in ({'rule': 'high-risk free routes', 'value': 'allowed'}, {'rule': 'unknown areas', 'value': 'allowed'}, {'rule': 'anything else', 'value': 'refused'}):
        with pytest.raises(st.AdditionError):
            st.compose_addition(SAMPLE, 'rules', [rule])


@pytest.mark.parametrize('items,why', [
    ([{'area': 'Money', 'default_risk': 'low'}], 'already exists'),                 # an existing area cannot be changed by an addition
    ([{'area': 'New thing', 'default_risk': 'sometimes'}], 'default risk'),
    ([{'area': '', 'default_risk': 'low'}], 'needs an area'),
    ([RISK] * 6, 'between 1 and 5'),
    ([], 'between 1 and 5'),
    (['not an object'], 'must be an object'),
])
def test_bad_additions_are_refused(items, why):
    with pytest.raises(st.AdditionError, match=why):
        st.compose_addition(SAMPLE, 'risk', items)


def test_table_breaking_characters_are_neutralized():
    new = st.compose_addition(SAMPLE, 'risk', [{'area': 'Odd | name\nwith newline', 'default_risk': 'low', 'route': 'a | b', 'examples': 'x'}])
    row = next(l for l in new.split('\n') if 'Odd' in l)
    assert row.count('|') == SAMPLE.split('\n')[SAMPLE.split('\n').index(next(l for l in SAMPLE.split('\n') if l.startswith('| Money')))].count('|')
    assert '\n' not in row


def test_the_verifier_catches_removed_lowered_dropped_and_loosened():
    assert any('removed or changed' in p for p in st.additive_problems(SAMPLE, SAMPLE.replace('| Money | `routes/billing.py` | high |', '| Money | `routes/billing.py` | low |')))
    assert any('lowered' in p or 'removed' in p for p in st.additive_problems(SAMPLE, SAMPLE.replace('| Money | `routes/billing.py` | high |', '| Money | `routes/billing.py` | medium |')))
    assert any('dropped' in p for p in st.additive_problems(SAMPLE, SAMPLE.replace('| `apps/web` | `npm run type-check && npm test && npm run build` | |\n', '')))
    loosened = SAMPLE + '\n- high-risk free routes: allowed\n'
    assert any('loosened' in p for p in st.additive_problems(SAMPLE, loosened))


# ------------------------------------------------------------------------------------- proposing
def test_a_proposal_freezes_the_diff_and_the_file_it_was_made_against(secured, repo):  # noqa: F811
    with secured.app.state.sessions() as s:
        row = sp.propose(s, 'hermes:op', 1, repo, 'risk', [RISK], 'Email sending is high risk.')
        assert row.status == 'pending' and row.base_sha256 == st.inspect(repo)['sha256'] and '+| Email sending' in row.patch
        again = sp.propose(s, 'hermes:op', 1, repo, 'risk', [RISK], 'Same thing again.')
        assert again.id == row.id                                                    # the same addition is not proposed twice


def test_a_repository_without_a_standards_file_gets_no_proposal(secured, tmp_path):  # noqa: F811
    (tmp_path / 'empty').mkdir()
    with secured.app.state.sessions() as s:
        with pytest.raises(sp.ProposalError, match='no docs/development/standards.md'):
            sp.propose(s, 'hermes:op', 1, tmp_path / 'empty', 'risk', [RISK], 'x')


# --------------------------------------------------------------------------------------- deciding
def test_approval_commits_on_a_new_branch_and_touches_nothing_else(secured, repo, tmp_path):  # noqa: F811
    head, branch_before = git(repo, 'rev-parse', 'HEAD'), git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')
    with secured.app.state.sessions() as s:
        row = sp.propose(s, 'hermes:op', 1, repo, 'risk', [RISK], 'Email sending is high risk.')
        done = sp.decide(s, tmp_path / 'data', row.id, True, 'op', repo)
        result = json.loads(done.result)
    assert done.status == 'applied' and result['branch'] == f'standards/{row.id}-risk'
    assert git(repo, 'rev-parse', 'HEAD') == head and git(repo, 'rev-parse', '--abbrev-ref', 'HEAD') == branch_before    # the current branch did not move
    assert (repo / FILE).read_text() == SAMPLE and git(repo, 'status', '--porcelain') == ''                          # nor did any file
    assert '| Email sending |' in git(repo, 'show', f'{result["branch"]}:{FILE}') and git(repo, 'rev-parse', result['branch']) == result['commit']
    assert git(repo, 'log', '-1', '--format=%s', result['branch']).startswith('Standards: Email sending')
    assert git(repo, 'worktree', 'list').count('\n') == 0, 'the temporary worktree is removed'
    assert git(repo, 'remote') == '', 'nothing is ever pushed'


def test_approval_refuses_when_the_file_changed_after_the_proposal(secured, repo, tmp_path):  # noqa: F811
    with secured.app.state.sessions() as s:
        row = sp.propose(s, 'hermes:op', 1, repo, 'risk', [RISK], 'x')
        (repo / FILE).write_text(SAMPLE + '\nA later human edit.\n')
        done = sp.decide(s, tmp_path / 'data', row.id, True, 'op', repo)
    assert done.status == 'failed' and 'changed after this was proposed' in json.loads(done.result)['reason']
    assert 'standards/' not in git(repo, 'branch', '--list')


def test_a_rejected_proposal_changes_nothing_and_cannot_be_decided_twice(secured, repo, tmp_path):  # noqa: F811
    with secured.app.state.sessions() as s:
        row = sp.propose(s, 'hermes:op', 1, repo, 'risk', [RISK], 'x')
        assert sp.decide(s, tmp_path / 'data', row.id, False, 'op', repo).status == 'rejected'
        with pytest.raises(sp.ProposalError, match='not waiting'):
            sp.decide(s, tmp_path / 'data', row.id, True, 'op', repo)
    assert git(repo, 'branch', '--list') == '* main'


def test_a_failed_commit_leaves_no_branch_or_worktree_and_says_why(secured, repo, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    monkeypatch.setenv('GIT_CONFIG_SYSTEM', '/dev/null')
    for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL', 'EMAIL'):
        monkeypatch.delenv(key, raising=False)
    subprocess.run(['git', '-C', str(repo), 'config', '--unset', 'user.name'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', '--unset', 'user.email'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.useConfigOnly', 'true'], check=True)
    with secured.app.state.sessions() as s:
        row = sp.propose(s, 'hermes:op', 1, repo, 'risk', [RISK], 'x')
        done = sp.decide(s, tmp_path / 'data', row.id, True, 'op', repo)
    assert done.status == 'failed' and 'git could not do that' in json.loads(done.result)['reason']
    assert git(repo, 'branch', '--list') == '* main' and git(repo, 'worktree', 'list').count('\n') == 0
    assert not (tmp_path / 'data' / 'standards-proposals' / str(row.id)).exists()


# ------------------------------------------------------------------------------------- Hermes and routes
def make_project(secured, repo, owner):  # noqa: F811
    with secured.app.state.sessions.begin() as s:
        p = Project(document=json.dumps({'title': 'Standards test', 'working_dir': str(repo)}), state='draft', created_by=owner, created_at=0, updated_at=0)
        s.add(p)
        s.flush()
        return p.id


def test_hermes_needs_its_switch_and_can_only_propose(secured, tmp_path, repo):  # noqa: F811
    from tests.test_profiles import USER
    b, _ = paired(secured, tmp_path)
    profile = secured.get('/api/profile').json()
    pid = make_project(secured, repo, profile['owner'])
    assert call(b, 'standards', project_id=pid).status_code == 403                               # off by default
    pref(secured, allow_discord_standards=True)
    read = call(b, 'standards', project_id=pid).json()
    assert read['source'] == 'repository' and 'only propose ADDITIONS' in read['instructions']
    proposed = call(b, 'standards_propose', project_id=pid, section='risk', items=[RISK], summary='Email is high risk.').json()['proposal']
    assert proposed['status'] == 'pending' and proposed['created_by'].startswith('hermes:')
    assert (repo / FILE).read_text() == SAMPLE and git(repo, 'branch', '--list') == '* main'      # proposing changed nothing
    bad = call(b, 'standards_propose', project_id=pid, section='risk', items=[{'area': 'Money', 'default_risk': 'low'}], summary='lower it')
    assert bad.status_code == 422 and 'already exists' in bad.text
    assert call(b, 'standards_propose', project_id=pid, section='risk', summary='no items').status_code == 422
    other = make_project(secured, repo, 'someone-else')
    assert call(b, 'standards', project_id=other).status_code == 403


def test_the_operator_routes_list_and_decide(secured, tmp_path, repo):  # noqa: F811
    signed(secured)
    pid = make_project(secured, repo, 'op')
    with secured.app.state.sessions() as s:
        row = sp.propose(s, 'hermes:op', pid, repo, 'risk', [RISK], 'Email sending is high risk.')
        rid = row.id
    listing = secured.get(f'/api/standards/proposals?project_id={pid}').json()['proposals']
    assert [p['id'] for p in listing] == [rid] and '+| Email sending' in listing[0]['patch']
    done = secured.post(f'/api/standards/proposals/{rid}/approve').json()
    assert done['status'] == 'applied' and done['result']['branch'] == f'standards/{rid}-risk'
    assert secured.post('/api/standards/proposals/999/approve').status_code == 404
    assert secured.post(f'/api/standards/proposals/{rid}/reject').status_code == 409            # already decided


def test_the_plugin_knows_the_standards_actions():
    from types import SimpleNamespace
    from tests.test_profiles import native
    mod = native()
    assert {'section', 'items'} <= mod.FIELDS
    seen = {}
    mod.register(SimpleNamespace(register_tool=lambda **kw: seen.update(kw)))
    props = seen['schema']['parameters']['properties']
    assert {'standards', 'standards_propose'} <= set(props['action']['enum']) and 'section' in props and 'items' in props
    assert 'ADD to a repository standards file' in seen['schema']['description']
