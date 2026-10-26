"""Dated routing guidance, not benchmark scores, access grants or a model price list."""

VERIFIED = '2026-10-25'
OPENAI = 'https://developers.openai.com/api/docs/guides/model-selection'
ANTHROPIC = 'https://platform.claude.com/docs/en/models/haiku-5-5/overview'
RESEARCH = 'https://artificialanalysis.ai/models/recommend'


def _classification(model):
    """Class is an app routing heuristic. Unknown/provider aliases stay unclassified."""
    model = (model or '').removeprefix('openrouter/').removeprefix('anthropic/')
    if model in {'claude-haiku-5-5', 'gpt-6-luna'}:
        return {'class': 'focused', 'use': 'bounded edits, extraction, triage, routine checks',
                'speed': 'vendor describes latency/cost optimized', 'source': ANTHROPIC if model.startswith('claude') else OPENAI,
                'verified': VERIFIED, 'vision': True}
    if model in {'claude-sonnet-5-5', 'gpt-6.1-sol'}:
        return {'class': 'general', 'use': 'multi-file coding, integration, planning with competing requirements',
                'speed': 'vendor describes balanced capability and latency', 'source': ANTHROPIC if model.startswith('claude') else OPENAI,
                'verified': VERIFIED, 'vision': True}
    if model in {'claude-opus-5-5', 'gpt-6-astra'}:
        return {'class': 'deep', 'use': 'difficult reasoning, architecture, high consequence review',
                'speed': 'more reasoning/latency may be warranted; measure locally', 'source': ANTHROPIC if model.startswith('claude') else OPENAI,
                'verified': VERIFIED, 'vision': True}
    if model == 'google/gemma-4-31b-it:free':
        return {'class':'general','use':'multimodal understanding, coding/reasoning; validate endpoint tools and reliability',
                'speed':'provider hardware dependent; measure locally','source':'https://ai.google.dev/gemma/docs/core/model_card_4','verified':VERIFIED,'vision':True}
    if model == 'cohere/north-mini-code:free':
        return {'class':'focused','use':'bounded coding and terminal/tool tasks; not a general visual-design default',
                'speed':'provider describes a small active footprint; measure endpoint latency','source':'https://openrouter.ai/cohere/north-mini-code:free','verified':VERIFIED,'vision':None}
    # Existing configured/legacy candidates have no current comparative claim here.
    return {'class': 'unclassified', 'use': 'match dated provider facts, task evidence and operator notes',
            'speed': 'unknown until measured', 'source': None, 'verified': None, 'vision': None}


def policy(bias):
    name = 'Economy' if bias < 38 else 'Balanced' if bias < 63 else 'Capability'
    threshold = ('Allow focused models for well-specified work; optimize expected total cost including retries.' if bias < 38 else
                 'Use focused models for bounded work and general models for multi-step integration or ambiguous requirements.' if bias < 63 else
                 'Prefer general or deep models on ambiguous/critical work; a simple task may still use a focused model with a clear reason.')
    return (f'Operator model classification threshold {bias}/100: {name}. {threshold} '
            'This is a capability/cost threshold, not a provider preference, required model, percentage or permission to spend. '
            'Classify each task by specialty, complexity, risk, vision/tools/context needs and verification burden, then match an installed candidate. '
            'Use sourced capability facts, dated research, local task history and current billing/quota constraints. '
            'Explain fit, class, cost/latency tradeoff and any threshold exception in route_reason. '
            'Subscription quota is separate from paid API tokens; a free API policy does not itself prohibit an allowed membership route. '
            'Explicit operator story routes override this default. Unknown aliases have unknown specialty, not guaranteed vision or quality. '
            'Always name an explicit model and configured target. Planning quality is chosen separately from this slider. '
            'No approvals, provider access or fallback permission are created by a recommendation.')


def planning_routes():
    """Automatic planning has focused/general options independent of the story slider.
    Installation, billing, approval and route-class checks are applied by the caller.
    """
    return [{'agent': a, 'model': m} for a, m in (
        ('claude', 'claude-haiku-5-5'), ('codex', 'gpt-6-luna'),
        ('claude', 'claude-sonnet-5-5'), ('codex', 'gpt-6.1-sol'))]


def compact_nodes(nodes, max_chars=14000):
    """Prior proposals are suggestions, not saved scope. Never duplicate a full prior map."""
    import json
    rows = []
    for n in nodes:
        row = {k: n.get(k) for k in ('key', 'kind', 'title', 'depends_on', 'assignee', 'model', 'host_action', 'media_stage')}
        row['scope'] = (n.get('scope') or '')[:180]
        row['description'] = (n.get('description') or '')[:220]
        if len(json.dumps(rows + [row], ensure_ascii=False)) > max_chars:
            break
        rows.append(row)
    return {'previous_proposal_only': rows, 'omitted': len(nodes)-len(rows),
            'rule': 'Rebuild untouched work from current saved requirements; drop old proposal scope that was never requested. This summary grants no new permissions.'}


def classification(model, now=None):
    import time
    from datetime import datetime, timezone
    row=_classification(model)
    stamp=datetime.strptime(row['verified'],'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() if row['verified'] else None
    current=time.time() if now is None else now
    return {**row,'stale':stamp is None or current < stamp or current-stamp > 90*86400}
