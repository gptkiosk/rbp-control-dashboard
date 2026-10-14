"""Fresh, credential-free route catalog from the native agents' configuration."""
import json
import re
from pathlib import Path
import yaml

def _model(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', value) else ''

def read(settings):
    result = {a: {'models': [], 'targets': [], 'default': None} for a in ('hermes', 'openclaw')}
    for agent, suffix in (('hermes', '.hermes/config.yaml'), ('openclaw', '.openclaw/openclaw.json')):
        configured = getattr(settings, agent + '_config_path', None)
        if getattr(settings, 'environment', 'test') == 'test' and not configured: continue
        path = Path(configured) if configured else Path.home() / suffix
        try:
            if path.stat().st_size > 2_000_000: continue
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
        except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError):
            pass  # Never return raw configuration or parser diagnostics containing credentials.
    return result

def automatic_route(model):
    value = model.removeprefix('openrouter/')
    return model in {'openrouter/free', 'openrouter/openrouter/free'} or value.endswith(':free') or value == 'google/gemini-2.5-flash'
