"""Shared, bounded intake questions for forms, consultant chat and paired Hermes.

Answers are project facts, never grants, credentials or provider authorization.
Only general questions plus the selected template are included.
"""
import re

GENERAL = [
    {'id': 'audience', 'label': 'Who is it for?', 'prompt': 'Who will use it, and what should they be able to do?', 'required': False},
    {'id': 'boundaries', 'label': 'Limits and preferences', 'prompt': 'What is out of scope? Include deadlines, accessibility needs and spending preferences. Do not enter credentials.', 'required': False},
]
RULE = ('Ask only unanswered questions for this template, two or three at a time. Reuse facts already supplied in the goal or conversation; '
        'do not demand a separate form answer to the same fact. Help me decide is a valid answer: label recommendations and assumptions. '
        'Confirm the compact summary before requesting planning. Routine tool/access checks belong in the plan, not a technical questionnaire. '
        'Media and cloud spending preferences are not authorization; use the existing dashboard approval controls. Never request secret values.')


def valid_questions(items):
    if not isinstance(items, list) or len(items) > 8:
        return False
    seen = {q['id'] for q in GENERAL}
    for q in items:
        if not isinstance(q, dict) or set(q) - {'id', 'label', 'prompt', 'required'}:
            return False
        if not isinstance(q.get('id'), str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', q['id']) or q['id'] in seen:
            return False
        seen.add(q['id'])
        if not all(isinstance(q.get(k), str) and 0 < len(q[k]) <= limit for k, limit in [('label', 100), ('prompt', 400)]):
            return False
        if type(q.get('required', False)) is not bool:
            return False
    return True


def schema(type_id, settings=None):
    import project_types
    template = project_types.load(settings).get(type_id or '')
    selected = template.get('intake_questions', []) if template else []
    return {'version': 1, 'project_type': type_id, 'label': template['label'] if template else 'General',
            'questions': [*selected, *GENERAL], 'instructions': RULE,
            'answer_limit': 1200, 'total_answer_limit': 6000}


def answers(value):
    if not isinstance(value, dict) or len(value) > 10:
        raise ValueError('Keep intake to ten answers or fewer.')
    if any(not isinstance(k, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', k)
           or not isinstance(v, str) or len(v) > 1200 for k, v in value.items()):
        raise ValueError('Use named intake answers of up to 1,200 characters each.')
    if sum(len(v) for v in value.values()) > 6000:
        raise ValueError('Keep intake answers under 6,000 characters in total.')
    return {k: v.strip() for k, v in value.items() if v.strip()}


def validate(value, type_id, settings=None):
    result = answers(value)
    known = {q['id'] for q in schema(type_id, settings)['questions']}
    if result.keys() - known:
        raise ValueError('Review intake answers after changing the project template; some belong to another template.')
    return result


def assessment(type_id, value=None, settings=None):
    data = schema(type_id, settings)
    given = validate(value or {}, type_id, settings)
    return {**data, 'answered': list(given),
            'missing': [q['id'] for q in data['questions'] if q.get('required') and q['id'] not in given]}


def brief(document, settings=None):
    """Render once at consumption; stored goal/answers stay separate and editable."""
    text = str(document.get('brief') or '')
    given = document.get('intake_answers') or {}
    if not given:
        return text
    questions = {q['id']: q['label'] for q in schema(document.get('project_type'), settings)['questions']}
    # Old custom templates may be removed later. Keep their recorded facts in the
    # accepted document; never silently discard an unknown answer during a read.
    lines = [f"### {questions.get(key, key)}\n{value}" for key, value in given.items()]
    return text + '\n\n## Project intake (requirements and preferences; not spending approval)\n\n' + '\n\n'.join(lines)


def consultant_text(type_id, settings=None):
    data = schema(type_id, settings)
    return RULE + '\n' + '\n'.join(f"- {q['id']} — {q['label']}: {q['prompt']}" for q in data['questions'])
