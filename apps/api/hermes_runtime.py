"""Launch the MCD-owned shim using the installed Hermes interpreter, not its global config."""
from pathlib import Path
import shutil

SHIM = Path(__file__).resolve().parents[2] / 'integrations/hermes/mcd-run.py'

def command(argv):
    if len(argv) < 2 or argv[1] != 'chat': return argv
    binary = Path(shutil.which(argv[0]) or argv[0])
    try:
        with binary.open() as handle: first = handle.readline(1024).strip()
    except (OSError, UnicodeError):
        raise FileNotFoundError('Hermes launcher is unavailable.') from None
    interpreter = first.removeprefix('#!')
    if not first.startswith('#!') or not Path(interpreter).is_file() or 'python' not in Path(interpreter).name:
        raise FileNotFoundError('MCD requires a Python Hermes launcher to enforce assigned models.')
    return [interpreter, str(SHIM), *argv[1:]]
