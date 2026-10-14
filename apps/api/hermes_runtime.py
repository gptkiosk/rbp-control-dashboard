"""Launch the dashboard shim with an installed Hermes interpreter and pinned model guard."""
from pathlib import Path
import json
import shutil
import os

SHIM = Path(__file__).resolve().parents[2] / 'integrations/hermes/mcd-run.py'

def command(argv, managed_root=None):
    if len(argv) < 2 or argv[1] != 'chat': return argv
    binary = Path(shutil.which(argv[0]) or argv[0])
    try:
        with binary.open() as handle: first = handle.readline(1024).strip()
    except (OSError, UnicodeError):
        raise FileNotFoundError('Hermes launcher is unavailable.') from None
    interpreter = first.removeprefix('#!')
    if first.startswith('#!') and Path(interpreter).is_file() and 'python' in Path(interpreter).name:
        return [interpreter, str(SHIM), *argv[1:]]
    # Current Hermes publishes a shell bootstrap. Do not execute or parse arbitrary
    # shell launchers. Managed installs have an owner-checked dependency receipt.
    if managed_root is not None:
        import tool_install as ti
        try:
            root = Path(managed_root).resolve()
            managed = ti.managed_bin(root, 'hermes')
            if managed and binary.resolve() == Path(managed).resolve():
                cfg = ti.ToolsConfig(root=root, catalog_dir=Path(__file__).parent, platform_key='managed', home=Path.home())
                view = ti.installed_view(cfg, 'hermes')
                receipt = ti.read_receipt(cfg, 'hermes', view['current']['vid'])
                for item in receipt.get('external', []):
                    dependency = Path(item).resolve()
                    if dependency.parent != (cfg.hermes_home / 'installs').resolve():
                        continue
                    facts = json.loads(ti.read_regular(dependency / 'facts.json', 256*1024, 'Hermes dependency facts'))
                    environment = Path(facts['packages']['venv']['environment'])
                    python = environment / 'bin/python'
                    if not environment.resolve().is_relative_to(dependency) or not python.resolve().is_relative_to(root):
                        continue
                    if not python.is_file() or python.stat().st_uid != os.getuid():
                        continue
                    source = (cfg.comp_dir('hermes') / 'current/hermes-agent').resolve()
                    if not source.is_relative_to(root):
                        continue
                    bootstrap = 'import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); shim=sys.argv.pop(1); sys.argv[0]=shim; runpy.run_path(shim,run_name="__main__")'
                    return [str(python), '-I', '-c', bootstrap, str(source), str(SHIM), *argv[1:]]
        except (OSError, ValueError, KeyError, TypeError, ti.ToolError):
            pass
    raise FileNotFoundError('Dashboard requires a supported Python Hermes runtime to enforce assigned models.')
