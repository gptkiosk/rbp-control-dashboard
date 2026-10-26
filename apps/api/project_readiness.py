"""Project-specific coordinator preflight. Local reads only, no credentials, installs or project code."""
import os
import re
import shutil
import subprocess
from pathlib import Path


def _report(s, project, settings):
    import approval, projects, project_contract
    from dispatcher import Dispatcher
    from models import UserCredential
    d = projects.document(project)
    rows = []
    def add(id_, ready, detail, link, pending=False):
        rows.append({'id': id_, 'status': 'pending' if pending else 'ready' if ready else 'missing', 'detail': detail, 'link': link})
    root = approval.resolve_workdir(d['working_dir'], settings.workdir_roots)
    add('workspace', bool(root and os.access(root, os.W_OK)), 'Approved project workspace must exist and be writable.', f'/projects?project={project.id}&view=workspace')
    route = project_contract.preferred_route(d)
    agent = (route or {}).get('agent') or 'codex'
    # Inspect exactly the dispatcher's tool path rather than a login shell's PATH.
    env = Dispatcher._env(agent)
    text = project_contract.saved_text(d) + '\n' + '\n'.join(n.get('description', '') + '\n' + n.get('acceptance', '') for n in d.get('nodes', []))
    tools = {'git'}
    if d.get('project_type') in project_contract.WEBSITES or re.search(r'\b(node|npm|javascript)\b', text, re.I): tools.add('node')
    if project_contract.generated_media(d): tools.add('ffmpeg')
    for name in sorted(tools):
        add('tool-' + name, bool(shutil.which(name, path=env.get('PATH', ''))), f'{name} must be available in the selected agent/host runtime; use installed managed tools before adding software.', '/profile#system-tools' if name=='ffmpeg' else '/profile#agent-tools')
    if route:
        from agents import REGISTRY
        from route_reliability import allowed_class
        available = route['agent'] in REGISTRY and REGISTRY[route['agent']].available(settings) and projects.subscription(s, route['agent']) and allowed_class(s, settings, 'subscription')
        add('story-route', available, f'Saved route {route["agent"]} · {route["model"]} must be installed, configured for membership billing and allowed. Never replace it with free-only work silently.', '/profile#route-recovery')
    if project_contract.generated_media(d):
        saved = s.get(UserCredential, (project.created_by, 'fal')) is not None
        add('media-provider', saved, 'A saved fal credential is required for the dashboard only. This check reads presence, never the secret or provider.', '/profile#credentials-profile')
    repo = d.get('repository')
    named = re.search(r'(?:github\.com/|(?:repository|repo)\s*:\s*)([A-Za-z0-9_-]+/[A-Za-z0-9_.-]+)\b', project_contract.saved_text(d), re.I)
    if repo and not repo.get('repo'):
        add('repository', True, 'Dashboard-owned private repository/clone/branch setup will run at approved submission; do not duplicate it as an agent task.', f'/projects?project={project.id}', pending=True)
    elif (repo and repo.get('repo')) or named:
        import agent_git
        grant = agent_git.load(settings.agent_git_grants_file).get(project.id)
        target = repo.get('repo') if repo else named.group(1)
        target=target.rstrip('.,;)')
        if target.endswith('.git'): target=target[:-4]
        allowed = bool(grant and root and any(c.repo.lower() == target.lower() and c.dir==root.name for c in grant.clones))
        if allowed and root:
            try:
                branch=subprocess.run(['git','-C',str(root),'branch','--show-current'],env=env,capture_output=True,text=True,timeout=3,check=True).stdout.strip()
                allowed=branch not in {'','main','master'} and any(c.repo.lower()==target.lower() and c.branch==branch for c in grant.clones)
            except (OSError,subprocess.SubprocessError): allowed=False
        add('repository', allowed, 'The named repository needs an app-registered clone and a project branch grant. Naming it alone neither proves access nor approves creation.', f'/projects?project={project.id}')
    if d.get('project_type') in project_contract.WEBSITES:
        script = root / 'tools/verify-preview.sh' if root else None
        prepared = bool(script and script.is_file() and not script.is_symlink() and script.stat().st_size > 0)
        from project_types import _ancestors
        stories={n['key']:n for n in d.get('nodes',[]) if n.get('kind')=='story'}
        preparations={n['key'] for n in stories.values() if n.get('assignee') != 'human' and n.get('mode') == 'edit' and
                      'tools/verify-preview.sh' in (n.get('description','')+' '+n.get('acceptance',''))}
        actions=[n for n in stories.values() if n.get('host_action') in {'preview-verify','preview-review'}]
        setup=bool(preparations and actions and all(preparations.intersection(_ancestors(stories,n['key'])) for n in actions))
        add('preview', prepared, 'The dashboard supports fixed Verify/Start/Stop and authenticated proxy actions. The project must supply tools/verify-preview.sh before runtime review.', f'/projects?project={project.id}', pending=not prepared and setup)
    return {'project_id': project.id, 'revision': project.revision, 'checks': rows,
            'ready': all(r['status'] != 'missing' for r in rows),
            'instructions': 'Coordinator: resolve plan-level gaps through save/replan and recheck. Use the linked existing setup controls for missing host tools/credentials/grants; never invent access, execute project scripts here or request a host terminal from a remote operator. Pending setup is not completed evidence.'}


def prompt(s, project, settings, limit=1600):
    try:
        data = report(s, project, settings)
        return ('Coordinator setup check: ' + '; '.join(r['id'] + '=' + r['status'] + ': ' + r['detail'] for r in data['checks']) + '\n' + data['instructions'])[:limit]
    except Exception:  # Missing private setup tables/config must not masquerade as readiness.
        return 'Coordinator setup check unavailable. Use the readiness read and resolve the missing facts before dispatch; do not claim readiness.'


def report(s, project, settings):
    try:
        return _report(s, project, settings)
    except Exception:
        # Fail closed without echoing paths, native config or credential diagnostics.
        return {'project_id':project.id,'revision':project.revision,'ready':False,
                'checks':[{'id':'readiness-unavailable','status':'missing','detail':'Current setup could not be evaluated. Recheck setup and service health before dispatch.','link':'/profile#system-tools'}],
                'instructions':'Missing readiness evidence is not permission to dispatch or expand access.'}
