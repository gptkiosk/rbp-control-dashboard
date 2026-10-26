"""Operator-only project review and planning. Agent tokens cannot approve or dispatch."""
import json
import re
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, or_, select, text
from sqlalchemy.orm import Session
from deps import get_session
from dispatcher import remove_run_logs
from settings import get_settings
from models import Project, ProjectTask, Card, CardDependency, Run
from project_schemas import QueuedRouteChange, Route, AcceptDespiteReport, Close, Document, Save, Action, Replan, Retry, GoFree, ContinueOutput, Note, Accept, HandoffPolicy, Retier, RepairExecution, ModelLock, LowCostRetry, PayRetry
import agent_git
import project_preview
import projects
import standards

router=APIRouter(prefix='/api/projects')

def actor(request):
    if getattr(request.state,'agent_grant',None): raise HTTPException(403,'Projects require operator access.')
    return (getattr(request.state,'user',None) or {}).get('email','operator')

def write(s): s.execute(text('BEGIN IMMEDIATE'))

@router.get('')
def list_projects(request: Request,s: Session=Depends(get_session)):
    actor(request)
    rows=list(s.scalars(select(Project).order_by(Project.updated_at.desc(),Project.id.desc()).limit(200)))
    return {'projects':[{'id':p.id,'title':projects.document(p)['title'],'state':p.state,'revision':p.revision,'updated_at':p.updated_at} for p in rows]}

@router.post('',status_code=201)
def create_project(body: Document,request: Request,s: Session=Depends(get_session)):
    identity=actor(request);write(s)
    p=projects.create(s,body.model_dump(),get_settings(),identity);s.commit();return projects.detail(s,p)

class GitGrantIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    repo:str=Field(max_length=140)
    dir:str=Field(max_length=82)
    slug:str=Field(default='setup',max_length=41)
    confirm:bool=False

@router.get('/{project_id}/git-grant')
def git_grant(project_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);projects.get(s,project_id)
    grant=agent_git.load(get_settings().agent_git_grants_file).get(project_id)
    return {'clones':[{'dir':c.dir,'repo':c.repo,'branch':c.branch} for c in grant.clones] if grant else []}

@router.post('/{project_id}/git-grant',status_code=201)
def add_git_grant(project_id:int,body:GitGrantIn,request:Request,s:Session=Depends(get_session)):
    """Let agents commit and push ONE branch (project-<id>/<slug>) of ONE allowlisted repository for this project. Operator only, never from agent output."""
    who=actor(request);projects.get(s,project_id)
    if not body.confirm:raise HTTPException(422,'Confirm the exact repository, folder and branch first.')
    config=request.app.state.github.config()
    if config is None or body.repo.lower() not in {r.lower() for r in config.repos}:raise HTTPException(422,'That repository is not on this install\'s GitHub list.')
    try:grant=agent_git.add_clone(get_settings().agent_git_grants_file,project_id,body.repo,body.dir,body.slug)
    except agent_git.GrantError as exc:raise HTTPException(422,str(exc)) from None
    projects.memory(s,projects.get(s,project_id),'decision',f'Operator granted agents branch access: {body.repo} in folder {body.dir} on project-{project_id}/{body.slug}.',who);s.commit()
    return {'clones':[{'dir':c.dir,'repo':c.repo,'branch':c.branch} for c in grant.clones]}

@router.get('/consultant-context')
def consultant_context(working_dir:str,request:Request,project_type:str|None=None,s:Session=Depends(get_session)):
    actor(request)
    import project_types
    chosen=project_type if project_type and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}',project_type) else None
    packet=project_types.guidance_packet(chosen,get_settings())
    return {'text':projects.consultant_context(s,get_settings(),working_dir,chosen),
        'context_manifest':{k:v for k,v in packet.items() if k!='text'}}

@router.get('/coordinator')
def coordinator_read_view(request:Request,operation:str,project_id:int|None=None,task_id:int|None=None,
        working_dir:str='',project_type:str|None=None,s:Session=Depends(get_session)):
    import coordinator_read
    owner=actor(request)
    return coordinator_read.read(s,get_settings(),operation,owner,project_id=project_id,task_id=task_id,
        working_dir=working_dir,project_type=project_type)

class PacketImport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    working_dir:str=Field(min_length=1,max_length=500)
    copy_references:bool=True

@router.post('/packet-import',status_code=201)
async def inspect_packet(request:Request):
    """Upload a project packet (.zip) as the raw request body. It is validated and staged for review; nothing is created yet."""
    import project_packet_import as pi
    who=actor(request)
    declared=request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared)>pi.UPLOAD_LIMIT:
        raise HTTPException(413,f'A packet can be at most {pi.UPLOAD_LIMIT//1048576} MB.')
    data=bytearray()
    async for chunk in request.stream():
        data+=chunk
        if len(data)>pi.UPLOAD_LIMIT: raise HTTPException(413,f'A packet can be at most {pi.UPLOAD_LIMIT//1048576} MB.')
    return pi.inspect(get_settings(),bytes(data),who)

@router.post('/packet-import/{import_id}/create',status_code=201)
def create_from_packet(import_id:str,body:PacketImport,request:Request,s:Session=Depends(get_session)):
    """Create the continuation draft from a reviewed packet. No tasks, approvals, routes or grants carry over."""
    import project_packet_import as pi
    who=actor(request);write(s)
    p=pi.create(s,get_settings(),import_id,body.working_dir,body.copy_references,who);s.commit();return projects.detail(s,p)

@router.get('/{project_id}')
def get_project(project_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);return projects.detail(s,projects.get(s,project_id))

from workspace_schemas import Reservation, Handoff

@router.post('/{project_id}/workspace/reserve')
def reserve_workspace(project_id:int,body:Reservation,request:Request,s:Session=Depends(get_session)):
    import coordinator_read, workspace_handoff
    who=actor(request);write(s);p=coordinator_read.owned(s,project_id,who)
    result=workspace_handoff.reserve(s,p,get_settings(),body,who);s.commit();return result

@router.post('/{project_id}/workspace/handoff')
def record_workspace_handoff(project_id:int,body:Handoff,request:Request,s:Session=Depends(get_session)):
    import coordinator_read, workspace_handoff
    who=actor(request);write(s);p=coordinator_read.owned(s,project_id,who)
    result=workspace_handoff.record(s,p,get_settings(),body,who);s.commit();return result

@router.get('/{project_id}/standards')
def standards_for(project_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);return standards.resolve(projects.document(projects.get(s,project_id))['working_dir'],get_settings().data_dir)

@router.patch('/{project_id}')
def save(project_id:int,body:Save,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.save(s,p,body.document.model_dump(),body.revision,get_settings(),identity);s.commit();return projects.detail(s,p)

class Amendment(BaseModel):
    text:str=Field(min_length=1,max_length=4000)

@router.post('/{project_id}/amendments',status_code=201)
def amend(project_id:int,body:Amendment,request:Request,s:Session=Depends(get_session)):
    """Amend the brief of a project in progress. The approved plan does not change; later stories follow the amendment."""
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.amend_brief(s,p,body.text,identity);s.commit();return projects.detail(s,p)

class RouteAll(BaseModel):
    revision:int=Field(ge=1)
    agent:str=Field(pattern=r'^(claude|codex|grok|hermes|openclaw)$')
    model:str=Field(min_length=1,max_length=120)
    backups:list[Route]=Field(default_factory=list,max_length=5)

@router.post('/{project_id}/route-all')
def route_all(project_id:int,body:RouteAll,request:Request,s:Session=Depends(get_session)):
    """Use one route for every agent story, as a new revision the operator reviews."""
    identity=actor(request);write(s);p=projects.get(s,project_id)
    changed,skipped=projects.route_all(s,p,body.revision,body.agent,body.model,get_settings(),identity,[b.model_dump() for b in body.backups]);s.commit()
    return {**projects.detail(s,p),'routed':changed,'skipped':skipped}

class StandardsFix(BaseModel):
    revision:int=Field(ge=1)

@router.post('/{project_id}/standards-fix')
def standards_fix(project_id:int,body:StandardsFix,request:Request,s:Session=Depends(get_session)):
    """Raise risks to their area minimum and move high-risk stories off free routes, as a new revision the operator reviews."""
    identity=actor(request);write(s);p=projects.get(s,project_id)
    changes=projects.fix_standards(s,p,body.revision,get_settings(),identity);s.commit()
    return {**projects.detail(s,p),'fixed':changes}

@router.post('/{project_id}/plan')
def plan(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.plan(s,p,body,get_settings(),identity,getattr(getattr(request.app.state,'collector',None),'subagents',None));s.commit();return projects.detail(s,p)

@router.post('/{project_id}/replan')
def replan(project_id:int,body:Replan,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.replan(s,p,body,get_settings(),identity,getattr(getattr(request.app.state,'collector',None),'subagents',None));s.commit();return projects.detail(s,p)

@router.post('/{project_id}/cancel-replan')
def cancel_replan(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.cancel_replan(s,p,body.revision,identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/submit')
def submit(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.submit(s,p,body,get_settings(),identity,getattr(request.app.state,'github_config',None));s.commit();return projects.detail(s,p)

@router.post('/{project_id}/resume-plan')
def resume_plan(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.resume_plan(s,p,body.revision,get_settings(),identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/planning-tasks/{card_id}/retry')
def retry_planning_task(project_id:int,card_id:int,body:Retry,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.retry_planning_task(s,p,card_id,body,get_settings(),identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/memory',status_code=201)
def note(project_id:int,body:Note,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    if not body.text.strip(): raise HTTPException(422,'Write a project decision or note.')
    projects.memory(s,p,'decision',body.text.strip(),identity);s.commit();return projects.detail(s,p)

@router.get('/{project_id}/stories/{card_id}/host-preview')
def host_preview_status(project_id:int,card_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);p=projects.get(s,project_id);link=projects.binding(s,card_id);c=s.get(Card,card_id)
    if not link or link.project_id!=p.id or link.role!='story' or not c: raise HTTPException(404,'Story not found in this project.')
    base=f'/api/projects/{project_id}/stories/{card_id}/host-preview/content'
    return project_preview.describe(p,c,link,proxy_base=base)

class HostPreviewAction(BaseModel):
    action: str = Field(pattern=r'^(verify|serve|stop)$')

@router.post('/{project_id}/stories/{card_id}/host-preview')
def host_preview_action(project_id:int,card_id:int,body:HostPreviewAction,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);p=projects.get(s,project_id);link=projects.binding(s,card_id);c=s.get(Card,card_id)
    if not link or link.project_id!=p.id or link.role!='story' or not c: raise HTTPException(404,'Story not found in this project.')
    if projects.dependency_blocks(s,c.id): raise HTTPException(409,'Finish this story’s prerequisites first.')
    base=f'/api/projects/{project_id}/stories/{card_id}/host-preview/content'
    result=project_preview.run(p,c,link,body.action,proxy_base=base)
    write(s)
    outcome='passed' if result['ok'] else f"failed (exit {result['exit_code']})"
    projects.memory(s,p,'checkpoint',f"Dashboard host preview action `{body.action}` {outcome}.\n\n{result['output']}",identity,c.id)
    # A host verifier is an operator-started, exact-command run.  Replacing a
    # failed agent attempt with this successful receipt lets its normal handoff
    # review release dependents; it never auto-accepts the story.
    if body.action=='verify' and result['ok'] and c.assignee_type!='human':
        ended=int(time.time()); started=max(0,ended-int(result['duration_s']))
        receipt=Run(card_id=c.id,agent='host-preview',model_requested='host-preview',model_reported='host-preview',provider='dashboard',stage='succeeded',
                    started_at=started,ended_at=ended,duration_s=result['duration_s'],exit_code=0,working_dir=str(c.working_dir or projects.document(p)['working_dir']),
                    command=json.dumps(['bash','tools/verify-preview.sh','verify']),log_path='',result_text=result['output'],error=None)
        s.add(receipt);s.flush();c.column='review';c.updated_at=ended
        projects.memory(s,p,'proposal','Dashboard host verifier succeeded. Review this exact output and accept the handoff to release dependent work.',identity,c.id,receipt.id)
        result['run_id']=receipt.id
    s.commit()
    return result

@router.api_route('/{project_id}/stories/{card_id}/host-preview/content/{asset_path:path}',methods=['GET','HEAD'])
@router.api_route('/{project_id}/stories/{card_id}/host-preview/content',methods=['GET','HEAD'])
def host_preview_content(project_id:int,card_id:int,request:Request,s:Session=Depends(get_session),asset_path:str=''):
    actor(request);p=projects.get(s,project_id);link=projects.binding(s,card_id);c=s.get(Card,card_id)
    if not link or link.project_id!=p.id or link.role!='story' or not c: raise HTTPException(404,'Story not found in this project.')
    root=project_preview._root(p,c,link)
    status,body,content_type=project_preview.proxy(root,asset_path,request.method)
    return Response(content=body,status_code=status,media_type=content_type.split(';',1)[0],headers={'Cache-Control':'no-store'})

@router.post('/{project_id}/stories/{card_id}/accept')
def accept(project_id:int,card_id:int,body:Accept,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.accept_story(s,p,card_id,body,identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/accept-despite-report')
def accept_despite_report(project_id:int,card_id:int,body:AcceptDespiteReport,request:Request,s:Session=Depends(get_session)):
    """Accept a story whose agent reported it unfinished, with the operator's reason recorded in the ledger and the handoff."""
    identity=actor(request);write(s);p=projects.get(s,project_id)
    if body.revision is not None: projects.check_revision(p,body.revision)
    projects.accept_despite_report(s,p,card_id,body,identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/retry')
def retry(project_id:int,card_id:int,body:Retry,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    link=projects.binding(s,card_id);c=s.get(Card,card_id)
    if not link or link.project_id!=p.id or link.role!='story' or p.state not in {'active','complete'} or c.column not in {'failed','review','done'}:
        raise HTTPException(409,'Only a stopped story in an active or completed project may be rerun.')
    latest=s.scalar(select(Run).where(Run.card_id==card_id).order_by(Run.id.desc()).limit(1))
    reopening=c.column=='done'
    if p.state=='complete' and not reopening:
        raise HTTPException(409,'A completed project can only reopen an accepted final agent story.')
    if c.column in {'review','done'} and (c.assignee_type=='human' or not latest or latest.stage!='succeeded'):
        raise HTTPException(409,'Finish the current run or output approval before rerunning this story.')
    if reopening:
        # A dependent that has not started holds no handoff from this story, so reopening invalidates nothing. A started one does.
        started=s.scalar(select(CardDependency.card_id).join(Card,Card.id==CardDependency.card_id).where(
            CardDependency.depends_on_id==card_id,
            or_(Card.column.not_in(('backlog','queued')),
                exists().where(Run.card_id==Card.id))).limit(1))
        if started is not None:
            raise HTTPException(409,'A task that depends on this accepted story has already started. Review a new project revision instead of invalidating its handoff.')
    if body.route:
        chosen=body.route.model_dump()
        if chosen not in projects.approved_story_routes(p,link):
            raise HTTPException(422,'Choose an agent/model route from this story’s approved plan.')
        if not projects.REGISTRY[chosen['agent']].available(get_settings()):
            raise HTTPException(422,'The chosen agent is not installed.')
        manifest=json.loads(p.approved_manifest)
        node=next(n for n in manifest['document']['nodes'] if n['key']==link.node_key)
        paid=manifest.get('paid_retries',{}).get(link.node_key)
        paid_choice=bool(paid and chosen==paid['route'])
        if not projects.subscription(s,chosen['agent']) and not paid_choice:
            if not manifest.get('api_work_approved') or chosen not in node['routes']:
                raise HTTPException(422,'This route now uses API billing without the required story approval. Review a new project plan.')
        target=None
        if chosen['agent']=='openclaw':
            target=paid['agent_target'] if paid_choice else node.get('agent_target') or None
            configured=projects.native_routes.read(get_settings(),wait=True)['openclaw']['targets']
            if target and target not in {a['id'] for a in configured}:
                raise HTTPException(422,'The approved OpenClaw target is no longer configured. Review a new project plan.')
        previous={'agent':c.agent,'model':c.model}
        c.agent=chosen['agent'];c.model=chosen['model'];c.agent_target=target
        projects.memory(s,p,'decision',f'Operator selected approved retry route {chosen} instead of {previous} for the SAME story #{card_id}. Scope, workspace, dependencies and acceptance are unchanged; prior work remains unverified.',identity,card_id)
    projects.timeout_gate(s,p,c,latest,body.acknowledge_timeout,identity,'rerun')
    if latest: projects.retry_output(s,p,link,latest)
    if reopening:
        p.state='active';p.error=None
        projects.memory(s,p,'decision',f'Operator reopened final story #{card_id} for a new verification run. Earlier accepted run #{latest.id} and its handoff remain historical evidence; the new run requires review before project completion.',identity,card_id)
    c.column='queued';projects.memory(s,p,'decision','Operator explicitly retried story #'+str(card_id),identity,card_id)
    s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/continue-output')
def continue_output(project_id:int,card_id:int,body:ContinueOutput,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.continue_output(s,p,card_id,body,get_settings(),identity);s.commit();return projects.detail(s,p)

@router.get('/{project_id}/packet')
def project_packet_view(project_id:int,request:Request,refresh_source:bool=False,s:Session=Depends(get_session)):
    """The project's continuation packet, brought up to date. Writes only the app's private packet folder."""
    import coordinator_read, project_packet
    p=coordinator_read.owned(s,project_id,actor(request))
    return project_packet.view(s,p,get_settings(),refresh_source)

@router.get('/{project_id}/packet.zip')
def project_packet_zip(project_id:int,request:Request,include_media:bool=False,s:Session=Depends(get_session)):
    """Download the packet: documents, living docs and reference art; published media only when asked. No source code."""
    import coordinator_read, project_packet
    from fastapi.responses import StreamingResponse
    p=coordinator_read.owned(s,project_id,actor(request))
    handle,name,size=project_packet.export(s,p,get_settings(),include_media)
    def chunks():
        try:
            while part:=handle.read(65536): yield part
        finally: handle.close()
    return StreamingResponse(chunks(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{name}"','Content-Length':str(size),'Cache-Control':'no-store'})

@router.get('/{project_id}/context',response_class=PlainTextResponse)
def context(project_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request)
    name=f'{get_settings().product_short_name.lower()}-project-{project_id}-context.md'
    return PlainTextResponse(projects.context(s,projects.get(s,project_id)),headers={'Content-Disposition':f'attachment; filename="{name}"'})

@router.post('/{project_id}/close')
def close(project_id:int,body:Close,request:Request,s:Session=Depends(get_session)):
    """End a project without finishing it. Its state becomes `closed`, never `complete`; the reason and the whole
    ledger are kept, no new story starts, and its failed cards can then be removed from the board."""
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    if p.state=='closed': return projects.detail(s,p)
    if p.state not in {'active','paused','draft','review','planning_failed','dispatch_failed'}:
        raise HTTPException(409,'Only a project that is not mid-planning, not mid-dispatch and not already complete can be closed.')
    if projects.running_stories(s,p): raise HTTPException(409,'Cancel the story that is running first, then close the project.')
    p.state='closed';p.pipeline=None;p.error=None
    projects.memory(s,p,'decision',f'Project closed without finishing all stories. Reason: {body.reason.strip()}',identity)
    paths=projects.remove_tasks(s,p,identity) if body.remove_tasks else []
    s.commit();remove_run_logs(paths);return projects.detail(s,p)

@router.post('/{project_id}/remove-tasks')
def remove_tasks(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    """Take a closed project's tasks off the board. The project and its ledger stay."""
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    paths=projects.remove_tasks(s,p,identity)
    s.commit();remove_run_logs(paths);return projects.detail(s,p)

class DeleteIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    confirm:bool=False

@router.post('/{project_id}/delete')
def delete_project(project_id:int,body:DeleteIn,request:Request,s:Session=Depends(get_session)):
    """Delete a closed or completed project, with its tasks, ledger and saved records. The working folder and its files are kept."""
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    if not body.confirm: raise HTTPException(422,'Confirm the delete. It cannot be undone.')
    paths,pid,folder=projects.delete_project(s,p,get_settings())
    s.commit();remove_run_logs(paths);projects.forget_project_files(get_settings(),pid)
    return {'deleted':pid,'working_dir_kept':folder}

@router.get('/{project_id}/checks')
def plan_checks(project_id:int,request:Request,s:Session=Depends(get_session)):
    """What the project's type expects of a plan and where this plan falls short. Context-aware required findings block submission; inspection itself changes nothing."""
    actor(request);p=projects.get(s,project_id);doc=projects.document(p)
    import project_types
    kind=doc.get('project_type')
    return {'project_type':kind,'findings':project_types.check_document(doc,get_settings())}

@router.post('/{project_id}/pause')
def pause(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    import workspace_handoff
    identity=actor(request);write(s);p=projects.get(s,project_id)
    workspace_handoff.dispatch_control(s,p,body.revision,'pause',identity)
    s.commit();return projects.detail(s,p)

@router.post('/{project_id}/resume')
def resume(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    import workspace_handoff
    identity=actor(request);write(s);p=projects.get(s,project_id)
    workspace_handoff.dispatch_control(s,p,body.revision,'resume',identity)
    s.commit();return projects.detail(s,p)

@router.get('/{project_id}/stories/{card_id}/artifact')
def inspect_artifact(project_id:int,card_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);p=projects.get(s,project_id);link=projects.binding(s,card_id);c=s.get(Card,card_id)
    if not link or link.project_id!=p.id or link.role!='story' or c.column=='running':
        raise HTTPException(409,'Inspect a stopped story in this project.')
    m=json.loads(p.approved_manifest);ws=m.get('workspaces',{}).get(link.node_key)
    latest=s.scalar(select(Run).where(Run.card_id==card_id).order_by(Run.id.desc()).limit(1))
    # A stopped timeout/cancel can leave workspace changes for diagnosis, but it is
    # never a publishable story output.  Only a successful reviewable run may expose
    # the controlled output artifact.
    output=projects.inspect_output(p,link,latest.id) if latest and latest.stage in {'succeeded','awaiting_approval'} else None
    if not ws: return {'files':[],'diff':'','head':None,'output':output}
    if projects.approval.current_branch(projects.Path(c.working_dir))!=ws['branch']:
        raise HTTPException(409,'Restore the assigned story branch before reviewing artifacts.')
    return {**projects.workspaces.inspection(c.working_dir),'output':output}

@router.post('/{project_id}/stories/{card_id}/integration')
def integration(project_id:int,card_id:int,body:Accept,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    link=projects.binding(s,card_id);c=s.get(Card,card_id)
    if not link or link.project_id!=p.id or link.role!='story' or c.column!='failed' or p.state not in {'active','paused'}:
        raise HTTPException(409,'Review prerequisite integration on a failed project story.')
    m=json.loads(p.approved_manifest);ws=m.get('workspaces',{}).get(link.node_key)
    if not ws or not ws.get('integration_error'): raise HTTPException(409,'This story has no failed prerequisite integration.')
    if any(s.get(Card,dep).column!='done' for dep in projects.cards.dependency_ids(s,card_id)):
        raise HTTPException(409,'Accept prerequisites before confirming their integration.')
    if not body.summary.strip(): raise HTTPException(422,'Describe the verified prerequisite integration.')
    if projects.approval.current_branch(projects.Path(c.working_dir))!=ws['branch']:
        raise HTTPException(409,'Restore the assigned story branch before confirming integration.')
    projects.workspaces.git(c.working_dir,'merge-base','--is-ancestor',m['base_commit'],'HEAD')
    if body.snapshot: projects.workspaces.snapshot_reviewed(c.working_dir,body.files)
    projects.workspaces.artifact(c.working_dir,ws['branch'],m['base_commit'])
    ws.update(prepared=True,starting_commit=projects.workspaces.git(c.working_dir,'rev-parse','HEAD'),integration_error=None)
    p.approved_manifest=json.dumps(m);p.error=None
    projects.memory(s,p,'decision','Operator confirmed prerequisite integration on '+ws['branch']+'. Story still requires retry and its own definition-of-done review.\n'+body.summary,identity,card_id)
    s.commit();return projects.detail(s,p)


@router.post('/{project_id}/handoff-policy')
def handoff_policy(project_id:int,body:HandoffPolicy,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.set_handoff_policy(s,p,body,identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/retier')
def retier(project_id:int,body:Retier,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.retier_paused(s,p,body,identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/repair-execution')
def repair_execution(project_id:int,card_id:int,body:RepairExecution,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.repair_incomplete_execution(s,p,card_id,body,get_settings(),identity)
    s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/pay-retry')
def pay_retry(project_id:int,card_id:int,body:PayRetry,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.pay_retry(s,p,card_id,body,get_settings(),identity)
    s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/low-cost-retry')
def low_cost_retry(project_id:int,card_id:int,body:LowCostRetry,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.low_cost_retry(s,p,card_id,body,get_settings(),identity)
    s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/go-free')
def go_free(project_id:int,card_id:int,body:GoFree,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    link=projects.binding(s,card_id);c=s.get(Card,card_id)
    latest=s.scalar(select(Run).where(Run.card_id==card_id).order_by(Run.id.desc()).limit(1))
    if (not link or link.project_id!=p.id or link.role!='story' or link.revision!=p.revision or
        p.state!='active' or not projects.can_go_free(c,latest) or latest.id!=body.run_id):
        raise HTTPException(409,'Go Free requires the current failed run of a story that hit a subscription limit, or a provider timeout or limit on its OpenClaw free model, in an active project.')
    chosen={'agent':'openclaw','model':body.model,'agent_target':body.agent_target}
    if chosen not in projects.free_retry_routes(get_settings()):
        raise HTTPException(422,'Choose a configured OpenClaw target and OpenRouter :free model. Paid and Google BYOK routes are excluded.')
    if c.agent=='openclaw' and chosen not in projects.other_free_routes([chosen],c):
        raise HTTPException(422,'Choose a different free model: this one just failed for this story.')
    why='a subscription limit' if projects.subscription_limit(c,latest) else 'a provider timeout or limit on its free model'
    projects.timeout_gate(s,p,c,latest,body.acknowledge_timeout,identity,'another free model')
    manifest=json.loads(p.approved_manifest)
    manifest.setdefault('free_retries',{})[link.node_key]={'route':{'agent':'openclaw','model':body.model},
        'agent_target':body.agent_target,'source_run_id':latest.id,'approved_by':identity,'approved_at':projects.now()}
    p.approved_manifest=json.dumps(manifest)
    projects.retry_output(s,p,link,latest)
    c.agent='openclaw';c.model=body.model;c.agent_target=body.agent_target;c.column='queued'
    projects.memory(s,p,'checkpoint',f'Go Free after {why} on run #{latest.id}. Partial work is unverified. Read the workspace diff and previous run evidence before continuing the SAME story.\n'+(latest.result_text or ''),identity,card_id,latest.id)
    projects.memory(s,p,'decision',f'Operator initiated Go Free for SAME story #{card_id}: {chosen}. Only this pinned free model is authorized; no paid/Google BYOK or automatic route switching. Scope, workspace, dependencies and acceptance remain unchanged.',identity,card_id,latest.id)
    s.commit();return projects.detail(s,p)


@router.post('/{project_id}/model-lock')
def model_lock(project_id:int,body:ModelLock,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.set_model_lock(s,p,body,identity);s.commit();return projects.detail(s,p)


@router.post('/{project_id}/stories/{card_id}/route')
def queued_route(project_id:int,card_id:int,body:QueuedRouteChange,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.change_queued_route(s,p,card_id,body,get_settings(),identity)
    s.commit();return projects.detail(s,p)


@router.get('/{project_id}/readiness')
def project_readiness_view(project_id:int, request:Request, s:Session=Depends(get_session)):
    import project_readiness
    actor(request)
    return project_readiness.report(s,projects.get(s,project_id),get_settings())


@router.post('/{project_id}/repair-plan')
def repair_plan_defaults(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    result=projects.repair_plan_defaults(s,p,body.revision,get_settings(),identity)
    s.commit();return {**projects.detail(s,p),'repaired':result}
