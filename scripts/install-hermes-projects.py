#!/usr/bin/env python3
"""Install the portable native plugin. No credentials or identity are copied from MCD."""
import argparse, json, re, shutil, subprocess
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-home',type=Path,default=Path.home()/'.hermes')
    parser.add_argument('--hermes',default=str(Path.home()/'.local/bin/hermes'))
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]/'integrations/hermes/mcd-projects'
    target=args.hermes_home/'plugins/mcd-projects'
    if target.exists():
        if target.is_symlink() or any((target/name).is_symlink() for name in ('__init__.py','plugin.yaml')):raise SystemExit('Refused a symlinked plugin destination.')
        if any((target/name).exists() and (target/name).read_bytes()!=(source/name).read_bytes() for name in ('__init__.py','plugin.yaml')):
            raise SystemExit('Existing plugin differs; preserve it before installing this version.')
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name in ('plugin.yaml','__init__.py'):shutil.copyfile(source/name,target/name)
    # A custom toolset is not automatically included in the Discord core bundle.
    # Read and extend this single field; preserve all native routes and other toolsets.
    raw = subprocess.check_output([args.hermes,'config','get','platform_toolsets.discord'],text=True).strip()
    try: toolsets = json.loads(raw)
    except ValueError:
        toolsets = re.findall(r'^- ([A-Za-z0-9_-]+)\s*$',raw,re.M)
    if not isinstance(toolsets,list) or not toolsets or any(not isinstance(t,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',t) for t in toolsets):
        raise SystemExit('Could not read Discord toolsets safely; no native configuration was changed.')
    if 'mcd_projects' not in toolsets:
        subprocess.run([args.hermes,'config','set','platform_toolsets.discord',json.dumps([*toolsets,'mcd_projects'])],check=True,capture_output=True,text=True)
    subprocess.run([args.hermes,'plugins','enable','mcd-projects'],check=True)
    print('Pair your Discord identity from MCD Profile. No project execution permission was added.')

if __name__=='__main__':main()
