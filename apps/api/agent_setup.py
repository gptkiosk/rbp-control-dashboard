"""Coordinator setup done by the dashboard itself: check each selected platform, show the changes, apply them, verify.

No model is involved, so every run behaves the same. Stable start creates only what is missing: OpenClaw role agents from the
versioned templates in packs/agents and the shared project folders. Existing agents, files and folders are never changed.
"I'll configure the platforms myself" makes no changes at all and only reports what is ready."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from settings import REPO_ROOT

PLATFORMS = ('openclaw', 'claude', 'codex', 'grok')
NAMES = {'openclaw': 'OpenClaw', 'claude': 'Claude Code', 'codex': 'Codex', 'grok': 'Grok Build', 'hermes': 'Hermes'}
TEMPLATES = REPO_ROOT / 'packs/agents'
AGENT_TOOLS = '/profile#agent-tools'
BILLING = '/agents?action=billing'
_LOCK = threading.Lock()


class SetupError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _env():
    from legacy_adapters import LegacyAgentAdapter
    return LegacyAgentAdapter.env()


def run(argv, timeout=30):
    """(exit code, first 300 characters of output). Never raises; 127 means it could not start."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=_env())
        return done.returncode, ((done.stdout or '') + (done.stderr or '')).strip()[:300]
    except subprocess.TimeoutExpired:
        return 124, f'no answer within {timeout} seconds'
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return 127, ''


def agent_id(settings, role):
    return f'{settings.product_short_name.lower()}-oc-{role}'


def base_dir(settings, pref):
    """The folder setup works in: the managed project area when project workspaces are on, else the operator's working directory, else the first allowed root."""
    import projects
    scratch = projects.scratch_root(settings)
    if pref.coordinator_bootstrap.project_workspaces and scratch is not None:
        return Path(scratch)
    if pref.working_dir:
        return Path(pref.working_dir).expanduser()
    return next((Path(r).expanduser() for r in settings.workdir_roots if Path(r).expanduser().is_dir()), None)


def _openclaw_agents(settings):
    import native_routes
    return {t['id']: t for t in native_routes.read(settings).get('openclaw', {}).get('targets', [])}


def check_platform(settings, s, platform):
    """A deterministic readiness row for one platform: installed, starts, and has a route the dashboard may use."""
    from agents import REGISTRY
    import native_routes
    import projects
    spec = REGISTRY[platform]
    row = {'id': platform, 'name': NAMES[platform], 'state': 'ready', 'version': None, 'model': None, 'detail': '', 'link': None}
    if not spec.available(settings):
        return {**row, 'state': 'missing', 'detail': 'Not installed on this host. Install it from Agent tools, or untick it.', 'link': AGENT_TOOLS}
    code, out = run([spec.binary(settings), '--version'], timeout=15)
    if code != 0:
        said = out.splitlines()[0] if out else ''
        return {**row, 'state': 'needs_action', 'detail': f'Installed but did not start{f" ({said})" if said else ""}. Run its health check in Agent tools.', 'link': AGENT_TOOLS}
    found = re.search(r'(?<![\w.])v?(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.-]+)?)', out)
    row['version'] = found.group(1) if found else None
    if platform == 'openclaw':
        model = native_routes.read(settings).get('openclaw', {}).get('default')
        if not model:
            return {**row, 'state': 'needs_action', 'detail': 'OpenClaw has no default model. Set one in its own configuration (openclaw configure), then check again.', 'link': AGENT_TOOLS}
        return {**row, 'model': model, 'detail': f'Default model {model}.'}
    if not projects.subscription(s, platform):
        return {**row, 'state': 'needs_action', 'detail': 'Save its billing account as Subscription in Agents, Billing & rates, after signing in on this host. Until then the dashboard will not start it.', 'link': BILLING}
    return {**row, 'detail': 'Billing saved as Subscription. Its sign-in is proven by the validation project.'}


def _change(action, kind, target, detail, path=None, role=None):
    return {'action': action, 'kind': kind, 'id': target, 'detail': detail, 'path': path, 'role': role}


def plan(settings, s, pref):
    """What setup would do now. The digest changes whenever the checks or the changes do, so a stale preview cannot be applied."""
    choice = pref.coordinator_bootstrap
    checks = [check_platform(settings, s, p) for p in PLATFORMS if p in choice.platforms]
    ready = {c['id'] for c in checks if c['state'] == 'ready'}
    base = base_dir(settings, pref)
    changes, problems = [], []
    registered = _openclaw_agents(settings) if 'openclaw' in ready else {}
    if base is None or not base.is_dir():
        problems.append('Choose or enable an allowed project workspace in Settings first.')
    elif choice.mode == 'stable' and ready:  # nothing to set up until a platform can use it
        if 'openclaw' in ready:
            for role in choice.roles:
                target = agent_id(settings, role)
                folder = base / 'agents' / target
                if target in registered:
                    changes.append(_change('keep', 'agent', target, 'Already registered with OpenClaw; left unchanged.', role=role))
                else:
                    changes.append(_change('create', 'agent', target, f'Register OpenClaw agent {target} on OpenClaw’s default model, with its {role} guidance in {folder}.', str(folder), role))
        if choice.shared_project_memory:
            note = base / 'shared-memory' / 'README.md'
            changes.append(_change('keep' if note.exists() else 'create', 'file', 'shared-memory', 'Shared project memory notes.', str(note)))
        if choice.project_workspaces:
            folder = base / 'projects'
            changes.append(_change('keep' if folder.is_dir() else 'create', 'folder', 'projects', 'Project workspaces folder.', str(folder)))
    if choice.mode == 'custom' and 'openclaw' in ready and not registered:
        problems.append('OpenClaw has no registered agents. Add one with openclaw agents add, or switch to Stable start.')
    if not ready:
        problems.append('No selected platform is ready yet.')
    state = {'mode': choice.mode, 'checks': [[c['id'], c['state'], c['model']] for c in checks], 'changes': [[c['action'], c['id'], c['path']] for c in changes]}
    digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:16]
    pending = [c for c in changes if c['action'] == 'create']
    return {'mode': choice.mode, 'checks': checks, 'changes': changes, 'problems': problems, 'base': str(base) if base else None,
            'agents': sorted(registered), 'digest': digest, 'verified': bool(ready) and not pending and not problems, 'last': last(settings)}


def _record_path(settings):
    return Path(settings.data_dir) / 'agent-setup' / 'last.json'


def last(settings):
    try:
        return json.loads(_record_path(settings).read_text())
    except (OSError, ValueError):
        return None


def _template(settings, name):
    return (TEMPLATES / name).read_text().replace('{product}', settings.product_short_name)


def _write_new(path, text):
    """Create a file only when nothing is there. Returns False for an existing file, which is left as it is."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, 'x') as fh:
            fh.write(text)
        return True
    except FileExistsError:
        return False


def _apply_one(settings, change):
    path = Path(change['path'])
    if change['kind'] == 'folder':
        path.mkdir(parents=True, exist_ok=True)
        return 'Created.'
    if change['kind'] == 'file':
        _write_new(path, f'# Shared project memory\n\nNotes that every {settings.product_short_name} project may read. Hermes adds accepted handoffs here; agents read them, and write only when a story says so.\n')
        return 'Created.'
    kept = [n for n, src in (('SOUL.md', f'{change["role"]}/SOUL.md'), ('AGENTS.md', 'AGENTS.md')) if not _write_new(path / n, _template(settings, src))]
    from agents import REGISTRY
    code, out = run([REGISTRY['openclaw'].binary(settings), 'agents', 'add', change['id'], '--workspace', str(path), '--non-interactive', '--json'], timeout=60)
    if code != 0:
        said = out.splitlines()[0] if out else f'exit {code}'
        raise SetupError(f'openclaw agents add failed: {said}')
    return 'Registered.' + (f' Kept existing {", ".join(kept)}.' if kept else '')


def apply(settings, s, pref, digest):
    """Make the previewed changes. Refused when the preview is stale, in configure-myself mode, or while another apply runs."""
    if pref.coordinator_bootstrap.mode != 'stable':
        raise SetupError('Configure-myself mode makes no changes. Switch to Stable start to let the dashboard set things up.')
    if not _LOCK.acquire(blocking=False):
        raise SetupError('Setup is already running.')
    try:
        current = plan(settings, s, pref)
        if current['digest'] != digest:
            raise SetupError('Something changed since the preview. Review the changes again.')
        results = []
        for change in (c for c in current['changes'] if c['action'] == 'create'):
            try:
                results.append({'id': change['id'], 'outcome': 'done', 'detail': _apply_one(settings, change)})
            except (SetupError, OSError) as exc:
                results.append({'id': change['id'], 'outcome': 'failed', 'detail': str(exc)[:300]})
        record = {'at': int(time.time()), 'results': results}
        path = _record_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
        return plan(settings, s, pref)
    finally:
        _LOCK.release()


def validation_nodes(settings, result):
    """A small built-in project that proves each ready platform answers: one read-only story per platform, then the operator's review."""
    nodes, keys = [], []
    for check in (c for c in result['checks'] if c['state'] == 'ready'):
        platform = check['id']
        target = ''
        if platform == 'openclaw':
            preferred = agent_id(settings, 'developer')
            target = preferred if preferred in result['agents'] else (result['agents'][0] if result['agents'] else '')
            if not target:
                continue
        key = 'validate-' + platform
        who = f'OpenClaw agent {target}' if target else check['name']
        nodes.append(dict(key=key, title=f'Validate {who}', assignee=platform, agent_target=target, model='', mode='read',
            description='List the files in this project folder (there may be none). Reply with a short report: which agent and role you are, the model you run on if you know it, and the files you can see. Do not create, change or delete anything.',
            scope='Read-only. This project folder only. No network calls, installs or configuration changes.',
            acceptance='A short report arrives that names the agent and lists the visible files, and no file changed.',
            work_kind='test', size='xs', risk='low', estimate_minutes=10, area='setup',
            route_reason='Proves the route that Coordinator setup verified, with the smallest possible task.',
            rationale='Built-in validation story.', x=40, y=40 + 150 * len(nodes)))
        keys.append(key)
    nodes.append(dict(key='human-acceptance', title='Review the validation reports', assignee='human', model='', mode='read', depends_on=keys,
        description='Read each validation report. A platform that answered is ready for real projects. For one that failed, open its task, read the error, fix the sign-in, model or billing it names, and rerun it. Then start a real project from [Projects](/projects).',
        scope='Operator review of the validation reports.', acceptance='Each platform is recorded as working or as needing a named fix.',
        work_kind='review', size='xs', risk='low', estimate_minutes=10, area='setup', route_reason='The operator accepts setup.',
        rationale='Built-in validation story.', x=40, y=40 + 150 * len(nodes)))
    return nodes
