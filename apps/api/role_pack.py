"""Operator-assigned roles and reversible, marked native instruction blocks.

Role guidance never grants execution permission. All paths are checked and all previews
are bound to exact file content; backups remain in private dashboard state.
"""
from __future__ import annotations
import contextlib
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from agents import REGISTRY
from settings import REPO_ROOT

MAX_BYTES = 256 * 1024
ROLES = {'worker', 'reviewer', 'security', 'delegator'}

class RoleError(ValueError):
    pass

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def _checked(path: Path):
    path = path.absolute()
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise RoleError('Instruction and state paths must not contain symlinks.')
        try:
            item = component.stat()
        except FileNotFoundError:
            continue
        if component == path and not stat.S_ISREG(item.st_mode):
            raise RoleError('Expected a regular file.')
    return path

def _read(path):
    path = _checked(path)
    if not path.exists():
        return None
    item = path.stat()
    if item.st_uid != os.getuid() or item.st_size > MAX_BYTES:
        raise RoleError('File is not owned by this user or exceeds the role pack limit.')
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeError:
        raise RoleError('Instruction file must be UTF-8.') from None

def _write(path, text):
    _checked(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _checked(path)
    if text is None:
        path.unlink(missing_ok=True)
        return
    temp = path.parent / ('.role-' + secrets.token_hex(8))
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

class RoleStore:
    def __init__(self, settings, *, home=None, pack_dir=None):
        self.settings = settings
        self.home = Path(home) if home else Path.home()
        self.folder = settings.data_dir / 'roles'
        self.state = self.folder / 'assignments.json'
        self.backup = self.folder / 'rollback.json'
        self.pending = self.folder / 'pending.json'
        self.pack = Path(pack_dir) if pack_dir else REPO_ROOT / 'packs/roles/delegator'
        product = settings.product_short_name.lower()
        self.begin = f'\n\n<!-- {product}:delegator:start -->'
        self.end = f'<!-- {product}:delegator:end -->'

    @contextlib.contextmanager
    def locked(self):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = _checked(self.folder / 'lock')
        with os.fdopen(os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def available(self):
        return [agent for agent, spec in REGISTRY.items() if spec.available(self.settings)]

    def read(self):
        raw = _read(self.state)
        if raw:
            state = json.loads(raw)
            if set(state) != {'roles', 'workspace', 'targets'}:
                raise RoleError('Role assignment state is invalid.')
            return state
        return {'roles': {agent: 'delegator' if agent == 'hermes' else 'worker' for agent in self.available()}, 'workspace': '', 'targets': []}

    def delegator(self):
        agents = [agent for agent, role in self.read()['roles'].items() if role == 'delegator']
        if len(agents) > 1:
            raise RoleError('Multiple Delegators are not permitted.')
        agent = agents[0] if agents else None
        if agent and agent not in self.available():
            raise RoleError('The assigned Delegator is no longer installed.')
        return agent

    def status(self):
        state = self.read()
        available = self.available()
        return {**state, **self.customized(), 'available': available, 'delegator': next((a for a,r in state['roles'].items() if r == 'delegator'), None), 'rollback_available': self.backup.exists(), 'guidance_installed': bool(state['targets']), 'revision': _digest(state), 'recovery_required': self.pending.exists()}

    def target_paths(self, agent, workspace):
        targets = {'hermes': [self.home / '.hermes/SOUL.md', self.home / '.hermes/context/dashboard-delegator.md'], 'claude': [self.home / '.claude/CLAUDE.md'], 'codex': [self.home / '.codex/AGENTS.md']}
        if agent in targets:
            return targets[agent]
        if not workspace:
            raise RoleError('Grok/OpenClaw require an explicit agent workspace.')
        path = Path(workspace).absolute()
        for part in [*path.parents, path]:
            if part.is_symlink():
                raise RoleError('Workspace must not contain symlinks.')
        if not path.is_dir() or path.stat().st_uid != os.getuid():
            raise RoleError('Workspace must be an existing directory owned by this user.')
        roots = [Path(p).resolve() for p in self.settings.workdir_roots]
        if not any(path == root or path.is_relative_to(root) for root in roots):
            raise RoleError('Workspace must be within an allowed dashboard root.')
        return [path / 'AGENTS.md'] if agent == 'grok' else [path / 'SOUL.md', path / 'AGENTS.md']

    def _custom_state(self, name):
        """(text or None, problem or None) for the user's own copy of a pack file in <data>/roles/custom/."""
        mine = self.folder / 'custom' / name
        if not mine.exists() and not mine.is_symlink():
            return None, None
        shipped = (self.pack / name).read_text()
        tokens = set(re.findall(r'\$[a-z_]+', shipped))
        try:
            text = _read(mine)
            if not text or not text.strip():
                return None, 'empty'
            missing = sorted(t for t in tokens if t not in text)
            if missing:
                return None, 'missing ' + ', '.join(missing)
            from string import Template
            Template(text).substitute({t[1:]: '' for t in tokens})
        except (RoleError, ValueError, KeyError, OSError) as error:
            return None, str(error) or 'unusable'
        return text, None

    def source(self, name):
        """The text for a pack file: the user's own copy when there is a usable one, else the shipped file.

        An update replaces the shipped files, so a user's wording lives in <data>/roles/custom/<name> instead, where an update
        never goes. A copy that cannot be used (it drops a placeholder the app fills in, has a stray `$`, is empty or unreadable)
        is ignored and the shipped text is used, so a broken edit can never stop planning."""
        text, _ = self._custom_state(name)
        return text if text is not None else (self.pack / name).read_text()

    def customized(self):
        """Which pack files the user has replaced, and which of their copies are being ignored (with why)."""
        used, ignored = [], {}
        for path in sorted(self.pack.iterdir()):
            if not path.is_file() or path.name == 'VERSION':
                continue
            text, problem = self._custom_state(path.name)
            if text is not None:
                used.append(path.name)
            elif problem:
                ignored[path.name] = problem
        return {'custom': used, 'custom_ignored': ignored}

    NAMES = ('plan.txt', 'review.txt', 'dispatch.txt', 'coordinate.txt', 'SOUL.md', 'context.md')

    def version(self):
        """Which coordinator wording is in effect: the shipped version number, which files are the user's own, and a short hash of the effective
        text, so plans made under different wording can be compared."""
        import hashlib
        try:
            shipped = (self.pack / 'VERSION').read_text().strip()[:12] or '0'
        except OSError:
            shipped = '0'
        custom = self.customized()['custom']
        text = '\n'.join(self.source(name) for name in self.NAMES if (self.pack / name).exists())
        return {'shipped': shipped, 'custom': custom, 'sha': hashlib.sha256(text.encode()).hexdigest()[:12], 'label': f'v{shipped}' + ('+custom' if custom else '')}

    def guidance(self):
        files = ['SOUL.md', 'context.md']
        text = '\n\n'.join(self.source(name) for name in files)
        # A short `sk-` match also catches ordinary words such as "task-state".
        # Require a token-sized suffix while retaining the host-path and key checks.
        if re.search(r'/Users/|/home/|tailscale|tailnet|sk-[A-Za-z0-9]{16,}|BEGIN .*PRIVATE KEY', text, re.I):
            raise RoleError('The starter pack contains private host or credential material.')
        return text + '\n\nInstalled agents: ' + ', '.join(self.available()) + '\n'

    def strip(self, text):
        text = text or ''
        if text.count(self.begin) != text.count(self.end) or text.count(self.begin) > 1:
            raise RoleError('Malformed managed instruction block; repair it before applying.')
        if self.begin not in text:
            return text
        a = text.index(self.begin); b = text.index(self.end) + len(self.end)
        if b < a:
            raise RoleError('Malformed managed instruction block.')
        return text[:a] + text[b:]

    def preview(self, roles, workspace=''):
        if set(roles) - set(REGISTRY) or any(v not in ROLES for v in roles.values()):
            raise RoleError('Unknown agent or role.')
        delegates = [a for a,r in roles.items() if r == 'delegator']
        if len(delegates) > 1:
            raise RoleError('Assign at most one Delegator.')
        if delegates and delegates[0] not in self.available():
            raise RoleError('Install the Delegator before assigning it.')
        if self.pending.exists():
            raise RoleError('An interrupted assignment needs recovery before another preview.')
        state = self.read()
        current = [Path(p) for p in state['targets']]
        # Revalidate persisted targets against the previous assignment before reading.
        old = [a for a,r in state['roles'].items() if r == 'delegator']
        allowed_old = self.target_paths(old[0], state['workspace']) if old and current else []
        if set(current) != set(allowed_old):
            raise RoleError('Stored instruction targets are invalid.')
        target = self.target_paths(delegates[0], workspace) if delegates else []
        changes = []
        guidance = self.guidance() if delegates else ''
        for path in sorted(set(current + target)):
            before = _read(path)
            clean = self.strip(before)
            # Only the managed block changes; operator text remains byte-for-byte.
            after = clean + self.begin + '\n' + guidance + self.end if path in target else clean
            if before == after:
                continue
            changes.append({'path': str(path), 'before': before, 'after': after})
        next_state = {'roles': roles, 'workspace': workspace if delegates and delegates[0] in {'grok','openclaw'} else '', 'targets': [str(p) for p in target]}
        plan = {'state_before': _read(self.state), 'state_after': next_state, 'changes': changes}
        # Do not expose the operator's surrounding instruction text in preview/API responses.
        public_changes = []
        for change in changes:
            old_block = (change['before'] or '')[ (change['before'] or '').find(self.begin): ] if self.begin in (change['before'] or '') else ''
            if old_block:
                old_block = old_block[:old_block.index(self.end)+len(self.end)]
            new_block = self.begin + '\n' + guidance + self.end if Path(change['path']) in target else ''
            public_changes.append({'path': change['path'], 'diff': ''.join(difflib.unified_diff(old_block.splitlines(True),new_block.splitlines(True),fromfile='managed before',tofile='managed after'))})
        return plan, {'roles': roles, 'workspace': next_state['workspace'], 'changes': public_changes, 'plan_sha256': _digest(plan), 'notice': 'Role guidance does not authorize execution, billing changes or native delegation.'}

    def apply(self, roles, workspace, digest):
        with self.locked():
            plan, public = self.preview(roles, workspace)
            if public['plan_sha256'] != digest:
                raise RoleError('Assignment or instruction files changed. Review a new preview.')
            backup = {**plan, 'state_after_text': json.dumps(plan['state_after'], sort_keys=True)}
            _write(self.pending, json.dumps({**backup, 'backup_before': _read(self.backup)}))
            applied = []
            try:
                for change in plan['changes']:
                    _write(Path(change['path']), change['after']); applied.append(change)
                _write(self.state, backup['state_after_text'])
                _write(self.backup, json.dumps(backup))
                self.pending.unlink()
            except Exception:
                for change in reversed(applied):
                    _write(Path(change['path']), change['before'])
                _write(self.state, plan['state_before'])
                self.pending.unlink(missing_ok=True)
                raise
            return self.status()

    def recover(self):
        with self.locked():
            raw = _read(self.pending)
            if not raw:
                raise RoleError('No interrupted role assignment exists.')
            plan = json.loads(raw)
            previous = json.loads(plan['state_before']) if plan['state_before'] else {'roles':{}, 'workspace':'', 'targets':[]}
            allowed = set()
            for state in [previous, plan['state_after']]:
                delegates = [a for a,r in state['roles'].items() if r == 'delegator']
                if delegates and state['targets']:
                    allowed.update(str(p) for p in self.target_paths(delegates[0], state['workspace']))
            if any(change['path'] not in allowed for change in plan['changes']):
                raise RoleError('Recovery instruction targets are invalid.')
            if _read(self.state) not in {plan['state_before'], plan['state_after_text']}:
                raise RoleError('Role state changed after interruption; recovery refused.')
            for change in plan['changes']:
                if _read(Path(change['path'])) not in {change['before'], change['after']}:
                    raise RoleError('Operator instruction edits after interruption must be preserved; recovery refused.')
            for change in plan['changes']:
                _write(Path(change['path']), change['before'])
            _write(self.state, plan['state_before'])
            _write(self.backup, plan['backup_before'])
            self.pending.unlink()
            return self.status()

    def rollback(self):
        with self.locked():
            if self.pending.exists():
                raise RoleError('Recover the interrupted role assignment first.')
            raw = _read(self.backup)
            if not raw:
                raise RoleError('No role assignment backup is available.')
            backup = json.loads(raw)
            if _read(self.state) != backup['state_after_text']:
                raise RoleError('Role state changed since this backup.')
            previous = json.loads(backup['state_before']) if backup['state_before'] else {'roles':{}, 'workspace':'', 'targets':[]}
            after = backup['state_after']
            allowed = set()
            for state in [previous, after]:
                delegates = [a for a,r in state['roles'].items() if r == 'delegator']
                if delegates and state['targets']:
                    allowed.update(str(p) for p in self.target_paths(delegates[0], state['workspace']))
            if any(change['path'] not in allowed for change in backup['changes']):
                raise RoleError('Backup instruction targets are invalid.')
            for change in backup['changes']:
                if _read(Path(change['path'])) != change['after']:
                    raise RoleError('Instruction file changed since assignment. Rollback refused to preserve operator edits.')
            for change in backup['changes']:
                _write(Path(change['path']), change['before'])
            _write(self.state, backup['state_before'])
            self.backup.unlink()
            return self.status()
