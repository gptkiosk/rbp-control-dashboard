#!/usr/bin/env python3
"""Compare dashboard shared contracts and inventory platform differences without running either app."""
import argparse
import ast
import json
from pathlib import Path

SHARED_FILES = ['apps/api/route_reliability.py', 'apps/api/bootstrap_plan.py',
    'apps/api/routes/profiles.py', 'apps/api/routes/billing.py',
    'apps/web/src/lib/routeRecovery.ts', 'apps/web/src/lib/profile.ts',
    'apps/web/src/components/RouteRecoveryPanel.vue', 'apps/web/src/components/RouteRecoveryNotice.vue',
    'apps/web/src/components/ProjectPlanningRetryAction.vue', 'apps/web/src/components/TaskRetryAction.vue',
    'apps/api/tests/test_route_reliability.py', 'apps/web/src/__tests__/RouteRecoveryPanel.spec.ts',
    'apps/web/src/__tests__/ProjectPlanningRetryAction.spec.ts']
SHARED_FUNCTIONS = ['_queue', '_next_planning_route', 'planning_retry_routes', '_planning_route_allowed',
    '_retry_unusable_planning_result', 'plan', 'retry_planning_task', 'add_recovery_routes', 'submit']
SHARED_SCHEMAS = ['Route', 'Node', 'Document', 'Action', 'Retry', 'GoFree', 'LowCostRetry', 'PayRetry']


def normalized(value):
    for old, new in [('Raspberry Pi Control Dashboard','PRODUCT'), ('Mac Control Dashboard','PRODUCT'),
            ('rbp-control-dashboard','PRODUCT-REPO'), ('mac-control-dashboard','PRODUCT-REPO'),
            ('RCD','PRODUCT'), ('MCD','PRODUCT'), ('rcd','product'), ('mcd','product')]:
        value = value.replace(old,new)
    return value


def inventory(root):
    return {p.relative_to(root).as_posix():p for area in ['apps/api','apps/web/src','packs','docs/configuration']
        for p in (root/area).rglob('*') if p.is_file() and p.suffix in {'.py','.vue','.ts','.json','.md','.txt'}
        and not {'__pycache__','.venv','node_modules'}.intersection(p.parts)}


def definitions(root, file):
    tree = ast.parse(normalized((root/file).read_text()))
    return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}


def compare(root, peer):
    a,b = inventory(root),inventory(peer)
    same, branding, changed = [], [], []
    for name in sorted(a.keys() & b.keys()):
        x,y = a[name].read_text(),b[name].read_text()
        (same if x==y else branding if normalized(x)==normalized(y) else changed).append(name)
    failures=[]
    for name in SHARED_FILES:
        if not (root/name).is_file() or not (peer/name).is_file() or normalized((root/name).read_text())!=normalized((peer/name).read_text()):
            failures.append(name)
    for file,names in [('apps/api/projects.py',SHARED_FUNCTIONS),('apps/api/project_schemas.py',SHARED_SCHEMAS)]:
        x,y=definitions(root,file),definitions(peer,file)
        failures.extend(file+':'+name for name in names if name not in x or x.get(name)!=y.get(name))
    for tree in (root,peer):
        if 'TaskRetryAction' not in (tree/'apps/web/src/components/CardDetailPanel.vue').read_text():
            failures.append('TaskRetryAction is not mounted on a dashboard')
    return {'shared_contract_checks':len(SHARED_FILES)+len(SHARED_FUNCTIONS)+len(SHARED_SCHEMAS)+2,
        'shared_contract_failures':failures,'common_files':len(a.keys() & b.keys()),'identical':len(same),
        'branding_only':len(branding),'different_files':changed,'this_product_only':sorted(a.keys()-b.keys()),
        'peer_product_only':sorted(b.keys()-a.keys()),
        'limits':'Inventory differences require feature/platform review; matching source and fixtures do not certify hardware or live providers.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--peer',required=True,type=Path);p.add_argument('--report',type=Path)
    args=p.parse_args();result=compare(Path(__file__).resolve().parents[1],args.peer.resolve())
    if args.report: args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'different_files','this_product_only','peer_product_only'}},indent=2))
    raise SystemExit(bool(result['shared_contract_failures']))
