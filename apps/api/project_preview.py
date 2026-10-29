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
import subprocess
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
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            key, value = line.split('=', 1)
            values[key] = value
        pid, port = int(values['pid']), int(values['port'])
        if not PORT_MIN <= port <= PORT_MAX or pid < 1 or not re.fullmatch(r'[0-9a-f]{40}', values.get('sha', '')):
            return None
        os.kill(pid, 0)
    except (OSError, ValueError, KeyError):
        return None
    return {'pid': pid, 'port': port, 'sha': values['sha'], 'started': values.get('started', '')}


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
        done = subprocess.run(['bash', str(root / 'tools' / 'verify-preview.sh'), action], cwd=root, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=180, env=env)
        output = ((done.stdout or '') + (('\n' if done.stdout and done.stderr else '') + done.stderr if done.stderr else ''))[-MAX_OUTPUT:]
        missing = MISSING_TOOL.search(output)
        if done.returncode and missing:
            output += (f"\n\n{missing.group(1)} is not installed where this host action can run it. "
                       + ("Install Node.js from Agent tools in Settings, then run the verifier again." if missing.group(1) in {'node', 'npm', 'npx'}
                          else "Install it on this host, then run the verifier again."))
        result = {'action': action, 'ok': done.returncode == 0, 'exit_code': done.returncode,
                  'duration_s': round(time.time() - started, 2), 'output': output, 'state': _state(root)}
    except subprocess.TimeoutExpired as exc:
        result = {'action': action, 'ok': False, 'exit_code': 124, 'duration_s': round(time.time() - started, 2),
                  'output': ((exc.stdout or '') + '\nPreview action timed out after 180 seconds.')[-MAX_OUTPUT:], 'state': _state(root)}
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
