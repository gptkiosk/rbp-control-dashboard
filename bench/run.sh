#!/usr/bin/env bash
# One-command benchmark entry point. Creates bench/.venv on first use, then runs bench/run.py.
#   bench/run.sh                              # synthetic self-test (no network, no spend)
#   bench/run.sh --live --cost-cap-usd 2.00   # real runtimes (needs bench/config.json + OPENROUTER_API_KEY)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
venv="$here/.venv"
if [ ! -x "$venv/bin/python" ]; then
  python3 -m venv "$venv"
  "$venv/bin/python" -m pip install --quiet -r "$root/tests/adapter_conformance/requirements.txt"
fi
cd "$root"
exec "$venv/bin/python" "$here/run.py" "$@"
