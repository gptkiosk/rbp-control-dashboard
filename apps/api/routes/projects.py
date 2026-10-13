"""Operator-only project review and planning. Agent tokens cannot approve or dispatch."""
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from deps import get_session
from settings import get_settings
from models import Project, ProjectTask, Card, CardDependency, Run
from project_schemas import Document, Save, Action, Retry, ContinueOutput, Note, Accept, HandoffPolicy
import projects

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

@router.get('/{project_id}')
def get_project(project_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);return projects.detail(s,projects.get(s,project_id))

@router.patch('/{project_id}')
def save(project_id:int,body:Save,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.save(s,p,body.document.model_dump(),body.revision,get_settings(),identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/plan')
def plan(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.plan(s,p,body,get_settings(),identity,getattr(getattr(request.app.state,'collector',None),'subagents',None));s.commit();return projects.detail(s,p)

@router.post('/{project_id}/submit')
def submit(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.submit(s,p,body,get_settings(),identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/resume-plan')
def resume_plan(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.resume_plan(s,p,body.revision,get_settings(),identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/memory',status_code=201)
def note(project_id:int,body:Note,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    if not body.text.strip(): raise HTTPException(422,'Write a project decision or note.')
    projects.memory(s,p,'decision',body.text.strip(),identity);s.commit();return projects.detail(s,p)

@router.post('/{project_id}/stories/{card_id}/accept')
def accept(project_id:int,card_id:int,body:Accept,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id)
    projects.accept_story(s,p,card_id,body,identity);s.commit();return projects.detail(s,p)

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
    if reopening and s.scalar(select(CardDependency.card_id).where(CardDependency.depends_on_id==card_id).limit(1)) is not None:
        raise HTTPException(409,'This accepted story has dependent tasks. Review a new project revision instead of invalidating their handoffs.')
    if body.route:
        chosen=body.route.model_dump()
        if chosen not in projects.approved_story_routes(p,link):
            raise HTTPException(422,'Choose an agent/model route from this story’s approved plan.')
        if not projects.REGISTRY[chosen['agent']].available(get_settings()):
            raise HTTPException(422,'The chosen agent is not installed.')
        manifest=json.loads(p.approved_manifest)
        node=next(n for n in manifest['document']['nodes'] if n['key']==link.node_key)
        if not projects.subscription(s,chosen['agent']):
            if not manifest.get('api_work_approved') or chosen not in node['routes']:
                raise HTTPException(422,'This route now uses API billing without the required story approval. Review a new project plan.')
        target=None
        if chosen['agent']=='openclaw':
            target=node.get('agent_target') or None
            configured=projects.native_routes.read(get_settings())['openclaw']['targets']
            if target and target not in {a['id'] for a in configured}:
                raise HTTPException(422,'The approved OpenClaw target is no longer configured. Review a new project plan.')
        previous={'agent':c.agent,'model':c.model}
        c.agent=chosen['agent'];c.model=chosen['model'];c.agent_target=target
        projects.memory(s,p,'decision',f'Operator selected approved retry route {chosen} instead of {previous} for the SAME story #{card_id}. Scope, workspace, dependencies and acceptance are unchanged; prior work remains unverified.',identity,card_id)
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

@router.get('/{project_id}/context',response_class=PlainTextResponse)
def context(project_id:int,request:Request,s:Session=Depends(get_session)):
    actor(request);return projects.context(s,projects.get(s,project_id))

@router.post('/{project_id}/pause')
def pause(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    if p.state=='paused': return projects.detail(s,p)
    if p.state!='active': raise HTTPException(409,'Only active story execution can be paused.')
    p.state='paused';projects.memory(s,p,'decision','Dispatch paused; running stories may finish in Review. No new story starts.',identity)
    s.commit();return projects.detail(s,p)

@router.post('/{project_id}/resume')
def resume(project_id:int,body:Action,request:Request,s:Session=Depends(get_session)):
    identity=actor(request);write(s);p=projects.get(s,project_id);projects.check_revision(p,body.revision)
    if p.state!='paused': raise HTTPException(409,'This project is not paused.')
    p.state='active';projects.memory(s,p,'decision','Operator resumed the same approved project revision.',identity)
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
