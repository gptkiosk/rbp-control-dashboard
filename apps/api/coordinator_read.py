"""Channel-neutral coordinator reads. No dispatch, spend, credentials or status writes.

Discord and native MCP use their scoped identities; the web UI uses its signed-in
operator. Every project/task read checks ownership before returning project data.
"""
import json
from sqlalchemy import select
from fastapi import HTTPException
from models import Card, Project, ProjectTask, Run
import project_types
import model_profiles
import projects
import failure_mining

OPERATIONS = ('capabilities', 'types', 'intake_questions', 'context', 'models', 'status', 'task', 'workspace', 'repository_intake')


def capabilities():
    return {
        'context_mode': 'general_plus_selected_type',
        'reads': list(OPERATIONS),
        'workflow': [
            {'feature': 'intake_and_planning', 'discord_actions': ['intake_questions', 'intake', 'get', 'save', 'plan'], 'operator_link': '/projects'},
            {'feature': 'diagnostics', 'discord_actions': ['failures', 'failure', 'task', 'status'], 'operator_link': '/telemetry'},
            {'feature': 'pause_resume', 'discord_actions': ['pause_dispatch', 'resume_dispatch'], 'operator_link': '/projects'},
            {'feature': 'replan_routes', 'discord_actions': [], 'operator_link': '/projects'},
            {'feature': 'preview_verify_start_stop', 'discord_actions': [], 'operator_link': '/projects'},
            {'feature': 'media_generate_select_publish', 'discord_actions': [], 'operator_link': '/projects?view=media'},
            {'feature': 'acceptance_and_dispatch', 'discord_actions': [], 'operator_link': '/projects'},
            {'feature': 'model_evidence', 'discord_actions': ['models'], 'operator_link': '/telemetry'},
            {'feature': 'workspace_handoff', 'discord_actions': ['workspace', 'reserve_workspace', 'record_handoff'], 'operator_link': '/projects?view=workspace'},
            {'feature': 'repository_intake', 'discord_actions': ['repository_intake'], 'operator_link': '/projects'},
        ],
        'instructions': 'Use supported actions only. An empty discord_actions list means use the operator link; never invent a tool or substitute terminal commands. Approved execution and human decisions remain enforced by the dashboard.'}


def owned(s, pid, owner):
    if not pid:
        raise HTTPException(422, 'Choose a project ID.')
    p = projects.get(s, pid)
    if p.created_by != owner:
        raise HTTPException(403, 'This project belongs to another profile.')
    return p


def read(s, settings, operation, owner, *, project_id=None, task_id=None, working_dir='', project_type=None):
    if operation == 'capabilities':
        return capabilities()
    if operation == 'types':
        return {'types': project_types.listing(settings)}
    p = owned(s, project_id, owner) if project_id else None
    if operation == 'intake_questions':
        import project_intake
        d = projects.document(p) if p else {}
        return project_intake.assessment(d.get('project_type', project_type), d.get('intake_answers'), settings)
    if operation == 'repository_intake':
        import repository_intake
        return repository_intake.inspect(settings, projects.document(p)['working_dir'] if p else working_dir)
    if operation == 'workspace':
        import workspace_handoff
        data = workspace_handoff.view(s, p or owned(s, project_id, owner), settings, working_dir)
        return {**data, 'packet': workspace_handoff.packet(data)}
    if operation == 'context':
        d = projects.document(p) if p else {}
        wd, kind = d.get('working_dir', working_dir), d.get('project_type', project_type)
        packet = project_types.guidance_packet(kind, settings)
        return {'text': projects.consultant_context(s, settings, wd, kind),
                'context_manifest': {k:v for k,v in packet.items() if k != 'text'}}
    if operation == 'models':
        catalog = projects.execution_catalog(settings, bias=projects.document(p)['planning_bias'] if p else 50)
        return {'guidance': model_profiles.guidance_text(s, settings.data_dir, catalog),
                'research': model_profiles.research_status(settings.data_dir),
                'instructions': 'Rank only configured approved routes. Match task kind, risk, tools and context size; prefer the smallest proven adequate model. Treat dated research as evidence, not authorization.'}
    if operation == 'status':
        p = p or owned(s, project_id, owner)
        links = list(s.scalars(select(ProjectTask).where(ProjectTask.project_id==p.id,
            ProjectTask.role=='story').order_by(ProjectTask.card_id.desc()).limit(100)))
        cards = [s.get(Card, link.card_id) for link in links]
        return {'project_id': p.id, 'revision': p.revision, 'state': p.state,
                'project_type': projects.document(p).get('project_type'),
                'tasks': [{'id': c.id, 'title': c.title[:200], 'state': c.column,
                    'superseded': projects.superseded_story(s,c), 'link': f'/tasks?card={c.id}'} for c in cards if c],
                'links': {'project':f'/projects?project={p.id}', 'media':f'/projects?project={p.id}&view=media'},
                'instructions': 'Current dashboard facts only. Superseded cards are history; explain the next meaningful decision using the project link.'}
    if operation == 'task':
        if not task_id:
            raise HTTPException(422, 'Choose a task ID.')
        c = s.get(Card, task_id)
        link = s.get(ProjectTask, task_id)
        if not c or not link:
            raise HTTPException(404, 'Choose a project task.')
        p = owned(s, link.project_id, owner)
        run = s.scalar(select(Run).where(Run.card_id==task_id).order_by(Run.id.desc()).limit(1))
        return {'task_id':c.id, 'project_id':p.id, 'revision':link.revision, 'state':c.column,
                'title':failure_mining.redact(c.title,200), 'superseded':projects.superseded_story(s,c,link),
                'agent':c.agent, 'model':c.model, 'run_id':run.id if run else None, 'run_stage':run.stage if run else None,
                'error':failure_mining.redact(run.error if run else '',400),
                'handoff':failure_mining.redact(run.result_text if run else '',2500),
                'depends_on': __import__('cards').dependency_ids(s,c.id),
                'links':{'task':f'/tasks?card={c.id}', 'project':f'/projects?project={p.id}', 'media':f'/projects?project={p.id}&view=media'},
                'instructions':failure_mining.UNTRUSTED}
    raise HTTPException(422, 'Unsupported coordinator read.')
