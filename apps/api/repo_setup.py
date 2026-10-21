"""A project's GitHub repository, set up by the dashboard itself when the operator submits the plan (no model, fixed order).

Steps: a private repository under the signed-in gh account, starter files on main, a clone in <project folder>/<name> on the branch
project-<id>/setup (pushed), the repository on this install's GitHub list, and the branch grant agents commit through. Each step is
skipped when it is already done, so a failed run can be retried. Agents never hold GitHub write access for any of this: the dashboard
runs `gh` and `git` as the operator, using the operator's own gh sign-in."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
GITIGNORE = """node_modules/
dist/
build/
.cache/
coverage/
.env
.env.*
!.env.example
media/candidates/
media/inbox/
.DS_Store
*.swp
"""


class RepoSetupError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _env():
    # The operator's own environment (HOME for gh's sign-in), without the dashboard's settings.
    return {k: v for k, v in os.environ.items() if not k.startswith('MAC_CONTROL_')}


def run(argv, cwd=None, timeout=120):
    """(exit code, output) of one command. Never raises; 127 means it could not start."""
    try:
        done = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=_env())
        return done.returncode, ((done.stdout or '') + (done.stderr or '')).strip()[:2000]
    except subprocess.TimeoutExpired:
        return 124, f'no answer within {timeout} seconds'
    except (OSError, subprocess.SubprocessError):
        return 127, ''


def gh_path(settings):
    configured = str(getattr(settings, 'gh_path', '') or '')
    if os.path.isabs(configured) and os.access(configured, os.X_OK):
        return configured
    from tool_install import managed_bin
    return managed_bin(getattr(settings, 'agent_tools_path', None), 'gh') or shutil.which('gh')


def _check(code, out, what):
    if code != 0:
        said = out.splitlines()[0] if out else f'exit {code}'
        raise RepoSetupError(f'{what} failed: {said}')


def setup(settings, project_id, working_dir, name, title, *, github_store=None, runner=run, remote_url=None):
    """Run every step that is not done yet. Returns {repo, folder, branch, done: [step sentences]}."""
    if not NAME_RE.fullmatch(name or ''):
        raise RepoSetupError('Use a repository name of lowercase letters, digits and dashes.')
    gh = gh_path(settings)
    if not gh:
        raise RepoSetupError('gh is not installed. Install it from Settings, Agent tools, then sign in with gh auth login on this host.')
    code, out = runner([gh, 'api', 'user', '--jq', '.login + " " + (.id|tostring)'])
    if code != 0 or len(out.split()) != 2:
        raise RepoSetupError('gh is not signed in on this host. Run gh auth login (GitHub.com, HTTPS, web) and try again.')
    account, user_id = out.split()
    full = f'{account}/{name}'
    root = Path(working_dir).expanduser()
    dest = root / name
    branch = f'project-{int(project_id)}/setup'
    url = remote_url(full) if remote_url else f'https://github.com/{full}.git'
    git = ['git', '-c', 'credential.helper=', '-c', f'credential.helper=!{gh} auth git-credential',
           '-c', f'user.name={account}', '-c', f'user.email={user_id}+{account}@users.noreply.github.com']
    done = []
    if not root.is_dir():
        raise RepoSetupError('The project folder does not exist yet.')

    if runner([gh, 'repo', 'view', full, '--json', 'name'])[0] != 0:
        _check(*runner([gh, 'repo', 'create', full, '--private', '--description', title[:300]]), 'Creating the private repository')
        done.append(f'Created private repository {full}.')
    if not dest.exists():
        _check(*runner([*git, 'clone', url, str(dest)], timeout=300), 'Cloning the repository')
        done.append(f'Cloned it into {dest}.')
    else:
        code, origin = runner(['git', '-C', str(dest), 'remote', 'get-url', 'origin'])
        if code != 0 or not origin.rstrip('/').removesuffix('.git').endswith(full) and origin.strip() != url:
            raise RepoSetupError(f'{dest} already exists and is not a clone of {full}. Rename or remove it, then try again.', 409)
    if runner(['git', '-C', str(dest), 'rev-parse', '--verify', 'HEAD'])[0] != 0:
        (dest / 'README.md').write_text(f'# {title}\n\nWork happens on the branch `{branch}`; changes reach `main` only after review.\n')
        (dest / '.gitignore').write_text(GITIGNORE)
        _check(*runner([*git, '-C', str(dest), 'add', 'README.md', '.gitignore']), 'Adding the starter files')
        _check(*runner([*git, '-C', str(dest), 'commit', '-m', 'Initial project setup: README and .gitignore']), 'The first commit')
        _check(*runner([*git, '-C', str(dest), 'branch', '-M', 'main']), 'Naming the main branch')
        _check(*runner([*git, '-C', str(dest), 'push', '-u', 'origin', 'main'], timeout=300), 'Pushing main')
        done.append('Pushed the starter files (README.md, .gitignore) to main.')
    if runner(['git', '-C', str(dest), 'rev-parse', '--verify', branch])[0] != 0:
        _check(*runner([*git, '-C', str(dest), 'checkout', '-b', branch]), 'Creating the setup branch')
    else:
        _check(*runner([*git, '-C', str(dest), 'checkout', branch]), 'Switching to the setup branch')
    _check(*runner([*git, '-C', str(dest), 'push', '-u', 'origin', branch], timeout=300), 'Pushing the setup branch')
    done.append(f'Agents work on {branch}.')

    if github_store is not None:
        status = github_store.status()
        repos = list(status.get('repos') or []) if status.get('state') in ('ready', 'disabled', 'unconfigured') else []
        if full.lower() not in {r.lower() for r in repos}:
            github_store.save({'version': 1, 'enabled': True, 'account': status.get('account') or account, 'repos': repos + [full],
                               'public_only': bool(status.get('public_only', False)), 'poll_seconds': int(status.get('poll_seconds') or 900)})
            done.append(f'Added {full} to this install\'s GitHub list.')
    import agent_git
    grant = agent_git.load(settings.agent_git_grants_file).get(int(project_id))
    if not grant or not any(c.dir == name for c in grant.clones):
        agent_git.add_clone(settings.agent_git_grants_file, int(project_id), full, name, 'setup')
        done.append(f'Granted agents the branch {branch} in {name}/.')
    return {'repo': full, 'folder': name, 'branch': branch, 'done': done}
