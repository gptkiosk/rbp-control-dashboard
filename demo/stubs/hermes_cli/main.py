"""Entry point the MCD Hermes shim runs (`runpy.run_module('hermes_cli.main')`): hand over to the stub."""
import runpy
import sys
from pathlib import Path

sys.argv = ["agent_stub.py", "hermes", *sys.argv[1:]]
runpy.run_path(str(Path(__file__).resolve().parents[1] / "agent_stub.py"), run_name="__main__")
