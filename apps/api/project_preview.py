"""Operator-triggered project preview actions.

A project preview binds to loopback.  It is started, verified and stopped only by
this host, through a narrow allowlist; the browser never receives a shell command
or an arbitrary command endpoint.  The dashboard proxy makes that loopback-only
preview viewable to a remote signed-in operator.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException

PORT_MIN, PORT_MAX = 41350, 41399
MAX_OUTPUT = 120_000
MAX_PROXY_BYTES = 20 * 1024 * 1024
# A script that starts a program the host cannot find fails with this line; name the program instead of leaving a traceback to decode.
MISSING_TOOL = re.compile(r"No such file or directory: '(node|npm|npx|python3|ffmpeg|git)'")
# Pilot 2026-10-29: a script that ran verify for every action, and wrote its own JSON state, left Open remote preview hidden. Stories get
# this text, and the dashboard checks Start and Stop after every passing verify of a plan that has a review story.
SCRIPT_CONTRACT = (
    'tools/verify-preview.sh takes one argument: verify, serve or stop. '
    'verify: start the site on 127.0.0.1 on a free port in 41350-41399, check it, stop it, and exit 0 only if every check passed. '
    'serve: start the site on 127.0.0.1 on a free port in 41350-41399 as a detached background process (nohup, or setsid where it exists; its output redirected '
    'to .preview/server.log, never to the script\'s own stdout), write .preview/preview.state, then exit 0 within 30 seconds while the server keeps running. '
    '.preview/preview.state is key=value lines or one JSON object with pid (the server process), port, sha (the git commit or a SHA-256 of the served files), '
    'and optionally started and status (running; any other value counts as stopped). '
    'stop: stop only the PID recorded in .preview/preview.state, then delete the file or set status to stopped. Never stop any other process. '
    'After every passing verify the dashboard runs serve, checks the recorded preview answers, then runs stop; if serve does not leave a running preview, verify fails.')
SMOKE_TIMEOUT = 30
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(root: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(root), threading.Lock())


def _node(manifest: dict, key: str) -> dict:
    return next((n for n in manifest.get('document', {}).get('nodes', []) if n.get('key') == key), {})


def _kind(node: dict) -> str | None:
    """Use explicit data for new plans, with a tight compatibility match for old plans."""
    action = node.get('host_action')
    if action in {'preview-verify', 'preview-review'}:
        return action
    title = str(node.get('title') or '').lower()
    if 'preview verifier' in title:
        return 'preview-verify'
    if ('persistent loopback preview' in title
            or ('persistent' in title and 'preview' in title)
            or ('dashboard-managed' in title and 'preview' in title)):
        return 'preview-review'
    return None


def _root(project, card, link) -> Path:
    manifest = json.loads(project.approved_manifest or '{}')
    node = _node(manifest, link.node_key)
    kind = _kind(node)
    if not kind:
        raise HTTPException(404, 'This story has no dashboard preview action.')
    raw = manifest.get('document', {}).get('working_dir')
    if not isinstance(raw, str) or not raw:
        raise HTTPException(409, 'The approved project workspace is unavailable.')
    project_root = Path(raw).expanduser().resolve()
    candidates = [Path(getattr(card, 'working_dir', '')).expanduser().resolve()] if getattr(card, 'working_dir', None) else []
    candidates.append(project_root)
    # Human stories deliberately have no card workspace. A project may hold its
    # approved checkout one level below its workspace, so search that bounded
    # location without allowing a path outside the approved root.
    if project_root.is_dir():
        candidates.extend(child for child in project_root.iterdir() if child.is_dir())
    for root in candidates:
        try:
            root.relative_to(project_root)
        except ValueError:
            continue
        if root.is_dir() and (root / 'tools' / 'verify-preview.sh').is_file():
            return root
    raise HTTPException(409, 'The approved workspace does not contain tools/verify-preview.sh.')


def _state(root: Path) -> dict | None:
    path = root / '.preview' / 'preview.state'
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
        if text.lstrip().startswith('{'):
            values = {k: str(v) for k, v in json.loads(text).items()}
        else:
            values = dict(line.split('=', 1) for line in text.splitlines() if line.strip())
        pid, port = int(values['pid']), int(values['port'])
        sha = values.get('sha') or values.get('source_sha', '')
        if values.get('status', 'running') != 'running':
            return None
        if not PORT_MIN <= port <= PORT_MAX or pid < 1 or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', sha):
            return None
        os.kill(pid, 0)
    except (OSError, ValueError, KeyError, AttributeError):
        return None
    return {'pid': pid, 'port': port, 'sha': sha, 'started': values.get('started', '')}


def _script(root: Path, action: str, env: dict, timeout: int) -> tuple[int, str, bool]:
    """Run one action. Output goes to files, not pipes: a server left running in the background would hold a pipe open and hang the call."""
    with tempfile.TemporaryFile('w+') as out, tempfile.TemporaryFile('w+') as err:
        child = subprocess.Popen(['bash', str(root / 'tools' / 'verify-preview.sh'), action], cwd=root, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, text=True, env=env, start_new_session=True)
        timed_out = False
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except OSError:
                    pass
                try:
                    child.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            code = 124
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(), err.read()
    return code, stdout + ('\n' if stdout and stderr else '') + stderr, timed_out


def _answers(state: dict) -> bool:
    try:
        conn = http.client.HTTPConnection('127.0.0.1', state['port'], timeout=5)
        conn.request('GET', '/')
        ok = conn.getresponse().status < 500
        conn.close()
        return ok
    except OSError:
        return False


def _serve_stop_check(root: Path, env: dict) -> tuple[bool, str]:
    """Start and stop the review preview once, so a plan finds out at verify, not at review, that Start leaves nothing running."""
    if _state(root):
        return True, 'Start/Stop check skipped: a review preview is already running.'
    code, output, timed_out = _script(root, 'serve', env, SMOKE_TIMEOUT)
    state = _state(root)
    lines = [f'$ tools/verify-preview.sh serve (exit {code})', output.strip()]
    problem = None
    if timed_out:
        problem = f'serve did not return within {SMOKE_TIMEOUT} seconds. It must start the server in the background and exit.'
    elif code:
        problem = 'serve failed.'
    elif not state:
        problem = 'serve returned, but .preview/preview.state does not record a running preview the dashboard can open.'
    elif not _answers(state):
        problem = f"serve recorded port {state['port']}, but nothing answers there."
    code, output, _ = _script(root, 'stop', env, SMOKE_TIMEOUT)
    lines += [f'$ tools/verify-preview.sh stop (exit {code})', output.strip()]
    left = _state(root)
    if left:
        # Only the PID this check's own serve recorded is stopped here.
        if state and left['pid'] == state['pid']:
            try:
                os.kill(left['pid'], signal.SIGTERM)
            except OSError:
                pass
        problem = problem or 'stop left the preview running.'
    if problem:
        lines += ['', 'Start/Stop check failed: ' + problem, 'Preview script contract: ' + SCRIPT_CONTRACT]
    else:
        lines += ['', 'Start/Stop check passed: serve left a running preview and stop ended it.']
    return problem is None, '\n'.join(l for l in lines if l is not None)


def describe(project, card, link, *, proxy_base: str) -> dict:
    manifest = json.loads(project.approved_manifest or '{}')
    node = _node(manifest, link.node_key)
    kind = _kind(node)
    if not kind:
        return {'available': False}
    root = _root(project, card, link)
    state = _state(root)
    actions = ['verify'] if kind == 'preview-verify' else ['serve', 'stop']
    return {
        'available': True,
        'kind': kind,
        'actions': actions,
        'running': state is not None,
        'state': state,
        'proxy_url': f'{proxy_base}/index.html' if state else None,
    }


def run(project, card, link, action: str, *, proxy_base: str) -> dict:
    root = _root(project, card, link)
    manifest = json.loads(project.approved_manifest or '{}')
    kind = _kind(_node(manifest, link.node_key))
    allowed = {'preview-verify': {'verify'}, 'preview-review': {'serve', 'stop'}}.get(kind, set())
    if action not in allowed:
        raise HTTPException(422, 'That host action is not approved for this story.')
    lock = _lock(root)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, 'A preview action is already running for this workspace.')
    started = time.time()
    try:
        # The same tool folders agents get, so a script that calls the managed Node.js from Agent tools finds it.
        from settings import managed_playwright_env, tool_search_dirs
        env = {'PATH': os.pathsep.join(tool_search_dirs()) or '/usr/bin:/bin', 'HOME': os.environ.get('HOME', ''), 'LANG': 'C.UTF-8',
               **managed_playwright_env()}
        code, output, timed_out = _script(root, action, env, 180)
        output = output[-MAX_OUTPUT:]
        missing = MISSING_TOOL.search(output)
        if code and missing:
            output += (f"\n\n{missing.group(1)} is not installed where this host action can run it. "
                       + ("Install Node.js from Agent tools in Settings, then run the verifier again." if missing.group(1) in {'node', 'npm', 'npx'}
                          else "Install it on this host, then run the verifier again."))
        if timed_out:
            output = (output + '\nPreview action timed out after 180 seconds.')[-MAX_OUTPUT:]
        ok = code == 0
        if ok and action == 'serve' and not _state(root):
            ok = False
            output += ('\n\nThe script returned, but .preview/preview.state does not record a running preview, so there is nothing to open. '
                       'The preview script needs rework to this contract: ' + SCRIPT_CONTRACT)
        if ok and action == 'verify' and any(_kind(n) == 'preview-review' for n in manifest.get('document', {}).get('nodes', [])):
            ok, check = _serve_stop_check(root, env)
            output = (output + '\n\n' + check)[-MAX_OUTPUT:]
        result = {'action': action, 'ok': ok, 'exit_code': code, 'duration_s': round(time.time() - started, 2), 'output': output, 'state': _state(root)}
    finally:
        lock.release()
    result['proxy_url'] = f'{proxy_base}/index.html' if result['state'] else None
    return result


def proxy(root: Path, asset_path: str, method: str = 'GET') -> tuple[int, bytes, str]:
    state = _state(root)
    if state is None:
        raise HTTPException(409, 'No approved preview is running for this workspace.')
    asset_path = asset_path.lstrip('/') or 'index.html'
    if '..' in asset_path.split('/') or '\\' in asset_path:
        raise HTTPException(404, 'Preview file not found.')
    conn = http.client.HTTPConnection('127.0.0.1', state['port'], timeout=15)
    try:
        conn.request(method, '/' + quote(asset_path, safe='/._-'))
        response = conn.getresponse()
        body = b'' if method == 'HEAD' else response.read(MAX_PROXY_BYTES + 1)
        if len(body) > MAX_PROXY_BYTES:
            raise HTTPException(413, 'Preview asset is too large to proxy.')
        content_type = response.getheader('Content-Type') or 'application/octet-stream'
        return response.status, body, content_type
    except OSError as exc:
        raise HTTPException(502, 'The preview is no longer reachable on its recorded loopback port.') from exc
    finally:
        conn.close()
