"""Fresh, credential-free route catalog from the native agents' configuration."""
import copy
import json
import re
import subprocess
import threading
import time
from pathlib import Path
import yaml

# OpenClaw can keep agents that its config file does not list (seen on a Pi: `openclaw agents list` showed agents the file omitted).
# Targets therefore also come from the CLI itself. Starting it takes seconds on a Pi, so a page never waits for it: reads get the last
# list at once and a stale one is refreshed in the background. Only callers that must be current (submitting a plan) pass wait=True.
CLI_TTL_S = 60
_cli = {'at': 0.0, 'key': None, 'agents': [], 'loaded': False, 'refreshing': False}
_cli_lock = threading.Lock()


def json_list(text):
    """The first JSON array in CLI output. Log lines such as "[plugins] ready" can come first, so a bare '[' is not enough."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\[\s*[\{\]]', text or ''):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, list):
            return value
    raise ValueError('no JSON list in the output')


def forget():
    """Mark the cached CLI agent list stale, after setup registers agents; the next read refreshes it."""
    with _cli_lock:
        _cli['at'] = 0.0


def _fetch(binary):
    """Ask the CLI. Never raises; a failure gives [] (and is cached, so a broken CLI is not retried on every request)."""
    found = []
    try:
        from dispatcher import Dispatcher
        done = subprocess.run([binary, 'agents', 'list', '--json'], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, env=Dispatcher._env('openclaw'))
        if done.returncode == 0:
            for row in json_list(done.stdout or ''):
                target = row.get('id') if isinstance(row, dict) else None
                if isinstance(target, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', target):
                    model = row.get('model')
                    found.append({'id': target, 'name': str(row.get('name') or row.get('identityName') or target)[:200],
                                  'model': _model(model.get('primary') if isinstance(model, dict) else model), 'default': bool(row.get('isDefault'))})
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        found = []
    return found


def _store(binary, found):
    with _cli_lock:
        _cli.update(at=time.monotonic(), key=binary, agents=found, loaded=True, refreshing=False)


def _refresh_in_background(binary):
    with _cli_lock:
        if _cli['refreshing']:
            return
        _cli['refreshing'] = True
    def work():
        try:
            _store(binary, _fetch(binary))
        finally:
            with _cli_lock:
                _cli['refreshing'] = False
    threading.Thread(target=work, name='openclaw-agents', daemon=True).start()


def _cli_agents(settings, wait=False):
    """[{id, name, model, default}] as `openclaw agents list --json` reports them; [] when it is absent, fails, is not known yet, or in tests.
    Without `wait` this never runs the CLI on the caller's thread."""
    if getattr(settings, 'environment', 'test') == 'test':
        return []
    try:
        from agents import REGISTRY
        spec = REGISTRY['openclaw']
        if not spec.available(settings):
            return []
        binary = spec.binary(settings)
    except Exception:
        return []
    with _cli_lock:
        known = _cli['loaded'] and _cli['key'] == binary
        fresh = known and time.monotonic() - _cli['at'] < CLI_TTL_S
        cached = list(_cli['agents']) if known else []
    if fresh:
        return cached
    if wait:
        found = _fetch(binary)
        _store(binary, found)
        return list(found)
    _refresh_in_background(binary)
    return cached


def _model(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', value) else ''

# agent -> ((path, mtime_ns, size), parsed entry): the last parsed version of each configuration file.
_parsed = {}


def read(settings, wait=False):
    result = {a: {'models': [], 'targets': [], 'default': None} for a in ('hermes', 'openclaw')}
    for agent, suffix in (('hermes', '.hermes/config.yaml'), ('openclaw', '.openclaw/openclaw.json')):
        configured = getattr(settings, agent + '_config_path', None)
        if getattr(settings, 'environment', 'test') == 'test' and not configured: continue
        path = Path(configured) if configured else Path.home() / suffix
        try:
            info = path.stat()
            if info.st_size > 2_000_000: continue
            # Parsed once per file version: route lists check hundreds of routes and each asks for this.
            stamp = (str(path), info.st_mtime_ns, info.st_size)
            if _parsed.get(agent, (None,))[0] == stamp:
                result[agent] = copy.deepcopy(_parsed[agent][1])
                continue
            raw = path.read_text()
            cfg = yaml.safe_load(raw) if agent == 'hermes' else json.loads(raw)
            models, targets = [], []
            if agent == 'hermes':
                model_cfg = cfg.get('model', {})
                default = _model(model_cfg.get('default') if isinstance(model_cfg, dict) else model_cfg)
                models.append(default)
                for key in ('fallback_providers', 'fallback_model'):
                    rows = cfg.get(key) or []
                    for row in ([rows] if isinstance(rows, dict) else rows):
                        if isinstance(row, dict): models.append(_model(row.get('model')))
            else:
                agents = cfg.get('agents', {})
                defaults = agents.get('defaults', {})
                def route(value):
                    if isinstance(value, str): return _model(value)
                    if isinstance(value, dict):
                        models.extend(_model(m) for m in value.get('fallbacks', []) if isinstance(m, str))
                        return _model(value.get('primary'))
                    return ''
                default = route(defaults.get('model'))
                models.extend(_model(m) for m in defaults.get('models', {}))
                models.append(default)
                for row in agents.get('list', []):
                    target = row.get('id')
                    if not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', target): continue
                    model = route(row.get('model')) or default
                    models.append(model)
                    targets.append({'id': target, 'name': str(row.get('name') or target)[:200], 'model': model, 'default': bool(row.get('default'))})
            result[agent] = {'models': list(dict.fromkeys(m for m in models if m)), 'targets': targets, 'default': default or None}
            _parsed[agent] = (stamp, copy.deepcopy(result[agent]))
        except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError):
            pass  # Never return raw configuration or parser diagnostics containing credentials.
    known = {t['id'] for t in result['openclaw']['targets']}
    for row in _cli_agents(settings, wait):
        if row['id'] not in known:
            model = row['model'] or result['openclaw']['default'] or ''
            result['openclaw']['targets'].append({**row, 'model': model})
            if model and model not in result['openclaw']['models']:
                result['openclaw']['models'].append(model)
    return result

def automatic_route(model):
    value = model.removeprefix('openrouter/')
    return model in {'openrouter/free', 'openrouter/openrouter/free'} or value.endswith(':free') or value == 'google/gemini-2.5-flash'
