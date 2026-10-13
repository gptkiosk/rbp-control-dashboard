"""Durable project notifications: claim before sending, uncertain sends never retry."""
import asyncio,json,time,uuid,re
from pathlib import Path
from sqlalchemy import select,update
from models import Project,ProjectDelivery,UserProfile
import profiles
from alerts import HermesSender

def queue(s,p,kind,settings,images=None):
    pref=profiles.prefs(s,p.created_by);profile=s.get(UserProfile,p.created_by)
    if not profile or not profile.discord_user_id or not pref.notify_plans or not pref.discord_channel_id:return None
    key=f'{p.id}:{p.revision}:{kind}'
    existing=s.scalar(select(ProjectDelivery).where(ProjectDelivery.source_key==key))
    if existing:return existing
    origin=pref.dashboard_origin or next((o for o in settings.auth_origins if o.startswith('https:')),settings.auth_origins[0])
    if kind=='ready':message=f'[MCD] Project #{p.id} plan is ready (revision {p.revision}).\nEdit it in Projects: {origin}/projects?project={p.id}\nWould you like a project diagram image? Ask Hermes for the diagram, or describe edits to the plan. Stories have not started.'
    elif kind=='failed':message=f'[MCD] Project #{p.id} planning stopped.\nReview: {origin}/projects?project={p.id}\nAsk Hermes for status or revise the brief. No stories started.'
    else:message=f'[MCD] Requested project #{p.id} diagram · revision {p.revision}.\nStory numbers show prerequisites. Edit with Hermes or in Projects: {origin}/projects?project={p.id}'
    row=ProjectDelivery(id=uuid.uuid4().hex,source_key=key,project_id=p.id,revision=p.revision,owner=p.created_by,destination='discord:'+pref.discord_channel_id,message=message,images=json.dumps(images or []),status='pending',created_at=int(time.time()))
    s.add(row);s.flush();return row

class ProjectMessenger:
    def __init__(self,sessions,settings,sender=None):
        self.sessions,self.settings=sessions,settings;self.sender=sender or HermesSender(settings.hermes_path);self.task=None
    def start(self):
        with self.sessions.begin() as s:
            for row in s.scalars(select(ProjectDelivery).where(ProjectDelivery.status=='delivering')):
                row.status='uncertain';row.error='Delivery interrupted. Check Discord; automatic retry disabled.'
        self.task=asyncio.create_task(self.run())
    async def stop(self):
        if self.task:self.task.cancel()
        if self.task:
            try:await self.task
            except asyncio.CancelledError:pass
    async def run(self):
        while True:
            try:
                worker=asyncio.create_task(asyncio.to_thread(self.tick))
                try:await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
            except Exception:pass  # Provider/private-file errors never enter logs or prompts.
            await asyncio.sleep(5)
    def tick(self):
        with self.sessions.begin() as s:
            for p in s.scalars(select(Project).where(Project.state.in_(['review','planning_failed']))):
                queue(s,p,'ready' if p.state=='review' else 'failed',self.settings)
            ids=list(s.scalars(select(ProjectDelivery.id).where(ProjectDelivery.status=='pending').limit(4)))
        for event_id in ids:
            with self.sessions.begin() as s:
                row=s.get(ProjectDelivery,event_id);pref=profiles.prefs(s,row.owner);profile=s.get(UserProfile,row.owner)
                p=s.get(Project,row.project_id)
                if not p or p.revision!=row.revision or (row.source_key.endswith(':ready') and p.state!='review'):
                    row.status='held';row.error='Project revision or stage changed.';continue
                if not profile or not profile.discord_user_id or not pref.notify_plans or 'discord:'+pref.discord_channel_id!=row.destination:
                    row.status='held';row.error='Profile delivery disabled or channel changed.';continue
                if row.created_at<int(time.time())-86400:row.status='expired';continue
                claimed=s.execute(update(ProjectDelivery).where(ProjectDelivery.id==event_id,ProjectDelivery.status=='pending').values(status='delivering'))
                if claimed.rowcount!=1:continue
                target,message,images=row.destination,row.message,json.loads(row.images)
                try:key=profiles.credential(s,row.owner,'discord',self.settings)
                except Exception:
                    row.status='held';row.error='Profile credential unavailable. Restore private vault access.';continue
            receipt=None
            try:
                if key:
                    import httpx
                    with httpx.Client(trust_env=False,follow_redirects=False,timeout=30) as client:
                        handles=[open(path,'rb') for path in images]
                        try:
                            args={'headers':{'Authorization':'Bot '+key}}
                            body={'content':message,'allowed_mentions':{'parse':[]}}
                            if handles:args.update(data={'payload_json':json.dumps(body)},files=[(f'files[{i}]',(Path(images[i]).name,h,'image/png')) for i,h in enumerate(handles)])
                            else:args['json']=body
                            r=client.post('https://discord.com/api/v10/channels/'+target.split(':')[1]+'/messages',**args)
                            if r.is_success and str(r.json().get('channel_id'))==target.split(':')[1]:
                                candidate=str(r.json().get('id') or '')
                                if re.fullmatch(r'[0-9]{16,22}',candidate):receipt=candidate
                        finally:
                            for h in handles:h.close()
                else:
                    # MEDIA paths originate only in the diagram renderer, never in project input.
                    receipt=self.sender(target,message+''.join('\nMEDIA:'+path for path in images))
            except Exception:pass
            with self.sessions.begin() as s:
                row=s.get(ProjectDelivery,event_id);row.message_id=receipt or None
                row.status='sent' if receipt else 'uncertain';row.error=None if receipt else 'Discord receipt not confirmed. Check channel; automatic retry disabled.'
