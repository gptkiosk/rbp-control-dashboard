"""Strict model JSON and field-only repairs of unapproved proposals. No execution rights."""
import copy
import json
from pydantic import ValidationError
from project_schemas import Node


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key[:80])
        result[key] = value
    return result


def loads(value):
    return json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda value: _reject(value))


def _reject(value):
    raise ValueError('Non-finite JSON number: ' + value)


# These labels classify already-described work; no route, permission, scope or graph edits.
REPAIR_FIELDS = {'work_kind', 'media_stage', 'media_batch', 'verification_stage'}


def field_repair(data):
    if not isinstance(data, dict) or set(data) != {'nodes'} or not isinstance(data['nodes'], list) or len(data['nodes']) > 100:
        return None
    keys, allowed = set(), []
    for node in data['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('key'), str) or node['key'] in keys:
            return None
        keys.add(node['key'])
        try:
            Node.model_validate(node)
        except ValidationError as exc:
            for error in exc.errors():
                loc = error['loc']
                if len(loc) != 1 or loc[0] not in REPAIR_FIELDS:
                    return None
                allowed.append({'key': node['key'], 'field': loc[0]})
    return {'source': copy.deepcopy(data), 'allowed': allowed} if allowed and len(allowed) <= 8 else None


def repair_prompt(repair):
    by_key = {n['key']: n for n in repair['source']['nodes']}
    rows = [{**a, 'value': repr(by_key[a['key']].get(a['field']))[:120],
             'title': by_key[a['key']].get('title', '')[:120],
             'description': by_key[a['key']].get('description', '')[:360]} for a in repair['allowed']]
    enums = {field: Node.model_json_schema()['properties'][field] for field in sorted(REPAIR_FIELDS)}
    return ('OUTPUT REPAIR (one attempt): Override the earlier response format for this repair only. '
            'Return ONLY {"repairs":[{"key":"existing key","field":"listed field","value":"valid label"}]}. '
            'Supply exactly one repair for each listed pair. The app preserves the entire source map and applies only these labels; '
            'do not return nodes, change scope, dependencies, models, access, or execute work. '
            'Allowed labels: ' + json.dumps(enums) + '\nInvalid fields: ' + json.dumps(rows))


def apply_repair(repair, response):
    if not isinstance(response, dict) or set(response) != {'repairs'} or not isinstance(response['repairs'], list):
        raise ValueError('Expected field-only repairs; the source map cannot be replaced.')
    allowed = {(a['key'], a['field']) for a in repair['allowed']}
    patched = copy.deepcopy(repair['source'])
    by_key = {n['key']: n for n in patched['nodes']}
    seen = set()
    for patch in response['repairs']:
        if not isinstance(patch, dict) or set(patch) != {'key', 'field', 'value'} or not isinstance(patch['key'], str) or not isinstance(patch['field'], str):
            raise ValueError('Invalid field repair.')
        pair = (patch['key'], patch['field'])
        if pair not in allowed or pair in seen:
            raise ValueError('Repair attempted an unlisted or duplicate field.')
        seen.add(pair)
        by_key[pair[0]][pair[1]] = patch['value']
    if seen != allowed:
        raise ValueError('Repair omitted an invalid field.')
    for node in patched['nodes']:
        Node.model_validate(node)
    return patched
