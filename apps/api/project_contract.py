"""Bounded checks of saved project intent. Plan text is data, never execution permission."""
import re

WEBSITES = {'local-website', 'gcp-hosted-website', 'website-property'}
RULES = ('Saved scope and explicit story-model choices outrank template examples and assignment bias. '
         'Never add a contact form, account, backend, tracking, container, cloud deployment or CI requirement unless the saved brief or selected delivery type needs it. '
         'If final media generation is requested, use distinct media_stage stories: inventory (agent writes slots), generate (human triggers dashboard fal.ai after spend acknowledgement), '
         'publish (human selects/publishes candidates), integrate (agent uses published files). Order each after the previous stage, and verification after integration. '
         'A selection/publish task is not a generation task. Existing-assets-only briefs need integration/verification but no paid generation. '
         'Asset prompts, purpose and sizing can be edited in Media Studio before any take is made; changing names/count/placements requires a reviewed inventory amendment. '
         'Inspect coordinator readiness and correct plan prerequisites using save/replan; use only linked approved setup controls for host changes. '
         'A missing credential, tool or branch grant is not authorization to create one. Routine setup checks are app-owned; do not invent repeated human command tasks.')


def saved_text(document):
    answers = document.get('intake_answers') or {}
    return '\n'.join([document.get('brief') or '', document.get('constraints') or '', *answers.values()])[:30000]


def generated_media(document):
    text = saved_text(document).lower()
    if re.search(r'\b(existing assets? only|use only existing|no (?:new |generated )?(?:media|art|images?|generation)|do not generate|don.t generate)\b', text):
        return False
    return bool(re.search(r'\bfal(?:\.ai)?\b|\bgenerat\w*.{0,65}\b(art\w*|media|images?|illustrations?|clips?|stills?)\b|\billustrated (?:web)?site\b', text, re.S))


def preferred_route(document):
    """Structured operator route wins; conservatively recognize explicit named story preferences.
    A bare model mention/reference is not a preference; ambiguous or negative prose is left for review.
    """
    if document.get('story_route'):
        return document['story_route']
    names = {'haiku': ('claude', 'claude-haiku-5-5'), 'sonnet': ('claude', 'claude-sonnet-5-5'),
             'luna': ('codex', 'gpt-6-luna'), 'terra': ('codex', 'gpt-5.6-terra')}
    found = []
    for sentence in re.split(r'[\n.!?;]', saved_text(document).lower()):
        if not re.search(r'\b(models?\s*:|prefer|use|stories|story route|subscription)', sentence):
            continue
        if re.search(r'\b(no|not|avoid|backup|fallback)\b.{0,30}\b(haiku|sonnet|luna|terra)\b', sentence):
            continue
        for name, route in names.items():
            if re.search(r'\b' + name + r'\b', sentence):
                found.append(route)
    unique = set(found)
    return dict(zip(('agent', 'model'), next(iter(unique)))) if len(unique) == 1 else None


def media_stage(node):
    if node.get('media_stage'):
        return node['media_stage']
    title = node.get('title', '').lower()
    # Compatibility for existing saved maps. Never infer generation from select/publish alone.
    if re.search(r'\b(?:media|assets?|artwork|illustrations?|slots?)\b.{0,35}\b(?:inventory|plan|slots?)\b|\binventory\b.{0,35}\b(?:media|assets?|artwork|illustrations?|slots?)\b|media/slots\.json', title): return 'inventory'
    if re.search(r'\b(generate|make)\b.{0,55}\b(media|art\w*|images?|illustrations?|stills?|clips?)\b', title): return 'generate'
    if re.search(r'\b(publish|select|approve)\b.{0,55}\b(media|art\w*|images?|illustrations?|stills?|clips?|candidates?)\b', title): return 'publish'
    if re.search(r'\b(integrat\w*|wire)\b.{0,55}\b(media|art\w*|images?|illustrations?|stills?|clips?)\b', title): return 'integrate'
    return None


def static_verification(node):
    """Recognize a distinct static check in either word order, never mere script authorship."""
    if node.get('host_action') or node.get('kind', 'story') != 'story':
        return False
    if node.get('verification_stage') == 'static':
        return True
    title = node.get('title', '').lower()
    return bool(re.search(r'\b(?:verif\w*|checks?|tests?|audit)\b', title) and
                re.search(r'\b(?:static|files?|assets?|links?|syntax)\b|file.level', title) and
                not re.search(r'\b(?:author|create|prepare|write|implement)\b', title))


def normalize_roles(node):
    """Fill unambiguous role labels on a new proposal only. Never edits content or graph."""
    row = dict(node)
    if row.get('kind', 'story') == 'story':
        if not row.get('media_stage'):
            stage = media_stage(row)
            if stage:
                row['media_stage'] = stage
        if row.get('media_stage') in {'generate', 'publish'} and not row.get('media_batch'):
            title = row.get('title', '').lower()
            reference = bool(re.search(r'\b(?:heroine|character)\b|\breference\b(?!-conditioned)', title))
            scenes = bool(re.search(r'\b(?:scenes?|pairs?|paired)\b|\b(?:page|world)\b.{0,35}\b(?:illustrations?|images?|artwork|stills?)\b', title))
            if reference != scenes:
                row['media_batch'] = 'reference' if reference else 'scenes'
        if not row.get('verification_stage') and static_verification(row):
            row['verification_stage'] = 'static'
    return row


def findings(document):
    from project_types import _ancestors
    stories = [n for n in document.get('nodes', []) if n.get('kind', 'story') == 'story']
    by_key = {n['key']: n for n in stories}
    found = []
    def add(id_, message, keys=(), severity='block'):
        found.append({'id': id_, 'severity': severity, 'message': message, 'stories': list(keys)})
    text = saved_text(document).lower()
    scope_rules = [('forms', r'\bforms?\b', r'\b(contact|signup|registration|feedback) form|\bform (handler|submission|redaction)'),
                   ('accounts', r'\baccounts?\b', r'\b(account|login|sign.?up|authentication) (system|flow|page|backend)|\buser registration'),
                   ('backend', r'\b(server|backend|api)\b', r'\b(application|api|http) (server|backend)|\bbackend (service|implementation|api)|\bapi endpoints?'),
                   ('tracking', r'\b(tracking|analytics)\b', r'\b(analytics|tracking|telemetry) (integration|setup|pipeline|events)')]
    for name, forbidden, feature in scope_rules:
        if not any(re.search(r'\b(no|without|exclude|avoid)\b.{0,160}' + forbidden, line) for line in re.split(r'[.!?\n]', text)):
            continue
        bad = [n['key'] for n in stories if re.search(feature, n.get('title', '').lower())
               and not re.search(r'\b(no|without|remove|absence|prevent|exclude)\b', n.get('title', '').lower())]
        if bad: add('scope-' + name, f'The plan adds {name} excluded by the saved brief. Remove that scope or explicitly revise the saved requirement.', bad)
    preferred = preferred_route(document)
    if preferred and preferred['agent'] in {'claude','codex'}:
        bad = [n['key'] for n in stories if n.get('assignee') in {'hermes', 'openclaw'} and
               not re.search(r'\bcapability exception\b', n.get('route_reason', ''), re.I)]
        if bad: add('saved-model-preference', f'Saved story preference is {preferred["agent"]} · {preferred["model"]}. Free/API primary assignments must be corrected or carry a specific capability exception for review.', bad)
    if preferred:
        exceptions=[n['key'] for n in stories if n.get('assignee') != 'human' and n.get('assignee') in {'claude','codex'} and (n.get('assignee'),n.get('model')) != (preferred['agent'],preferred['model'])]
        if exceptions: add('saved-route-exception','Review subscription routes differing from the saved primary preference; retain only justified capability exceptions.',exceptions,'warn')
        declared=[n['key'] for n in stories if 'capability exception' in n.get('route_reason','').lower()]
        if declared: add('declared-route-exception','Review the stated capability exceptions against the saved route and available tools before accepting these assignments.',declared,'warn')
    if generated_media(document):
        groups = {stage: [n for n in stories if media_stage(n) == stage] for stage in ('inventory', 'generate', 'publish', 'integrate')}
        for stage, nodes in groups.items():
            if not nodes: add('media-stage-' + stage, f'Requested generated artwork needs a distinct {stage} story. Selecting or publishing existing candidates does not generate them.')
            missing = [n['key'] for n in nodes if not n.get('media_stage')]
            if missing: add('media-role-label', 'Media work exists but needs its explicit media_stage label before submission; repair the label, not a duplicate story.', missing)
            wrong = [n['key'] for n in nodes if (n.get('assignee') == 'human') != (stage in {'generate', 'publish'})]
            if wrong: add('media-owner-' + stage, 'Generation/publication run through dashboard Media Studio decisions; agents inventory/integrate files and never receive the provider key.', wrong)
        for previous, following in zip(('inventory', 'generate', 'publish'), ('generate', 'publish', 'integrate')):
            first = {n['key'] for n in groups[previous]}
            bad = [n['key'] for n in groups[following] if not first.intersection(_ancestors(by_key, n['key']))]
            if bad: add('media-order-' + following, f'Media {following} must depend on {previous}; keep the paid generation and candidate decision in the correct order.', bad)
        first = {n['key'] for n in groups['integrate']}
        bad = [n['key'] for n in stories if (n.get('host_action') in {'preview-verify', 'preview-review'} or
               static_verification(n))
               and not first.intersection(_ancestors(by_key, n['key']))]
        if bad: add('media-before-final-verification', 'Final file/preview verification must follow integration of the published artwork, not a placeholder-only layout.', bad)
    if document.get('project_type') in {'local-website','gcp-hosted-website'}:
        # A template example or previous proposal is never a positive requirement.
        def requested(pattern):
            return any(re.search(pattern,line,re.I) and not re.search(r'\b(no|without|exclude|avoid|not needed|do not)\b',line,re.I)
                       for line in re.split(r'[.!?\n]',saved_text(document)))
        extras=[('form',r'\b(contact|signup|registration|feedback) form',r'\b(contact|signup|registration|feedback) form'),
                ('container',r'\b(docker|containers?|compose)\b',r'\b(dockerfile|containers?|compose)\b'),
                ('ci',r'\b(ci|continuous integration|github actions|pipeline)\b',r'\b(ci workflow|pipeline files|pipeline result|github actions)\b')]
        for label,wanted,feature in extras:
            if label in {'container','ci'} and document.get('project_type')!='local-website': continue
            if not requested(wanted):
                keys=[n['key'] for n in stories if re.search(feature,n.get('title',''),re.I) and not re.search(r'\b(remove|without|exclude|no)\b',n.get('title',''),re.I)]
                if keys:add('unrequested-'+label,'The selected website intake does not request '+label+' work. Remove the old/template scope or explicitly add the delivery requirement.',keys)
        preparations={n['key'] for n in stories if n.get('assignee')!='human' and n.get('mode')=='edit' and
                      'tools/verify-preview.sh' in (n.get('description','')+' '+n.get('acceptance',''))}
        actions=[n for n in stories if n.get('host_action') in {'preview-verify','preview-review'}]
        bad=[n['key'] for n in actions if not preparations.intersection(_ancestors(by_key,n['key']))]
        if bad:add('preview-script-author','Assign an agent Edit story to create the preview scripts/health output before the fixed dashboard host actions. A human Verify action cannot author a missing script.',bad)
        implementation={n['key'] for n in stories if n.get('work_kind')=='implement' and n.get('assignee')!='human'}
        checks=[n for n in stories if static_verification(n)]
        for n in checks:
            missing=implementation-_ancestors(by_key,n['key'])-{n['key']}
            if missing:add('implementation-before-final-check','Final static verification must follow every implementation story, including transitions and preview preparation.',[n['key'],*sorted(missing)])
        if document.get('repository'):
            required={n['key'] for n in stories if n.get('host_action')=='preview-review' or n.get('work_kind')=='docs'}
            for n in stories:
                if re.search(r'\bpush\b',n.get('title',''),re.I) and not required<=_ancestors(by_key,n['key']):
                    add('accepted-result-before-delivery','Branch delivery must follow final visual approval and project documentation.',[n['key']])
    if document.get('project_type') in WEBSITES:
        verifies={n['key'] for n in stories if n.get('host_action')=='preview-verify'}
        reviews=[n for n in stories if n.get('host_action')=='preview-review']
        file_checks={n['key'] for n in stories if static_verification(n)}
        if not file_checks: add('static-file-verification','Website preview needs static file/asset verification first; preparing the verifier script is a separate prerequisite.')
        bad=[key for key in verifies if not file_checks.intersection(_ancestors(by_key,key))]
        if bad: add('static-before-host-preview','The dashboard verification checkpoint must depend on static file/asset verification, not merely script preparation.',bad)
        wrong_owner=[n['key'] for n in stories if n.get('host_action') in {'preview-verify','preview-review'} and n.get('assignee')!='human']
        if wrong_owner: add('dashboard-preview-owner','Fixed dashboard host actions must use assignee human with no agent execution; the operator uses the in-app button and the app runs the approved script. Do not route a host action to a coding model.',wrong_owner)
        if not verifies: add('dashboard-preview-verify','Website verification needs explicit host_action preview-verify so the app exposes its fixed Verify button.')
        if not reviews: add('dashboard-preview-review','Website visual review needs explicit host_action preview-review so the app exposes authenticated Start/Open/Stop controls.')
        bad=[n['key'] for n in reviews if not verifies.intersection(_ancestors(by_key,n['key']))]
        if bad: add('dashboard-preview-order','Persistent visual review must depend on the dashboard verification checkpoint.',bad)
    repository=document.get('repository') or re.search(r'(?:github\.com/|(?:repository|repo)\s*:\s*)[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',saved_text(document),re.I)
    if document.get('project_type') in WEBSITES and repository:
        delivered=any(re.search(r'\bpush\b',n.get('title','')+' '+n.get('description',''),re.I) for n in stories)
        if not delivered: add('requested-remote-delivery','Repository-backed delivery needs a story that pushes the checked project branch and verifies the remote SHA; a local commit is insufficient. PR/CI work is conditional.')
    found.extend(reference_findings(document, stories, by_key))
    return found


def reference_first(document):
    text = saved_text(document)
    return generated_media(document) and bool(re.search(r'\b(?:heroine|character|style)\b.{0,70}\breference\b.{0,80}\b(?:first|before|followed by)\b|\bfirst\b.{0,70}\b(?:generate|publish|approve)\b.{0,70}\b(?:heroine|character|style)\b.{0,40}\breference\b', text, re.I))


def reference_findings(document, stories, by_key):
    from project_types import _ancestors
    if not reference_first(document):
        return []
    found = []
    def add(id_, message, keys):
        found.append({'id': id_, 'severity':'block', 'message':message, 'stories':keys})
    operations = [n for n in stories if media_stage(n) in {'generate', 'publish'}]
    missing = [n['key'] for n in operations if not n.get('media_batch')]
    if missing:
        add('media-batch-label', 'Reference-first art needs media_batch reference or scenes on each generation/publication story. Label the existing passes; do not merge them.', missing)
    reference_generate = {n['key'] for n in operations if n.get('media_batch')=='reference' and media_stage(n)=='generate'}
    reference_publish = {n['key'] for n in operations if n.get('media_batch')=='reference' and media_stage(n)=='publish'}
    scene_generate = {n['key'] for n in operations if n.get('media_batch')=='scenes' and media_stage(n)=='generate'}
    scene_publish = {n['key'] for n in operations if n.get('media_batch')=='scenes' and media_stage(n)=='publish'}
    if not all((reference_generate, reference_publish, scene_generate, scene_publish)):
        add('reference-first-passes', 'Use separate reference generation/publication and scene generation/publication passes; prose inside one Generate-all task is insufficient.', [n['key'] for n in operations])
    for keys, prerequisites, id_ in [(reference_publish, reference_generate, 'reference-publication-order'), (scene_generate, reference_publish, 'reference-before-scenes'), (scene_publish, scene_generate, 'scene-publication-order')]:
        bad = [key for key in keys if not prerequisites or not prerequisites <= _ancestors(by_key,key)]
        if bad:
            add(id_, 'Encode the published-reference to scene-generation chain in depends_on; each required prior pass must finish first.', sorted(bad))
    bad = [n['key'] for n in stories if media_stage(n)=='integrate' and (not scene_publish or not scene_publish <= _ancestors(by_key,n['key']))]
    if bad:
        add('scenes-before-integration', 'Final artwork integration must follow publication of all required scene batches.', bad)
    return found


def prompt(document, limit=2400):
    problems = findings(document)
    route = preferred_route(document)
    text = RULES
    if route: text += f'\nSaved primary story preference: {route["agent"]} · {route["model"]}. Prefer it to free routes; identify any genuine capability exception in route_reason.'
    if problems: text += '\nCorrect these proposed-plan defects: ' + '; '.join(f['id'] + ': ' + f['message'] for f in problems[:8])
    return text[:limit]
