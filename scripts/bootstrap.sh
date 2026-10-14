#!/usr/bin/env bash
# Rebuild the API venv from the lock file and the web app from package-lock.json.
# Required: Python 3.11+ (override with RCD_PYTHON), Node.js with npm. Optional tools
# (gh, macmon, tailscale, agent CLIs) are never needed for setup; see docs/getting-started.md.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

find_python() {
  local candidate
  for candidate in "${RCD_PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    [ -n "${candidate}" ] || continue
    command -v "${candidate}" >/dev/null 2>&1 || continue
    "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null || continue
    command -v "${candidate}"
    return 0
  done
  return 1
}

PYTHON="$(find_python)" || { echo "Python 3.11 or newer is required. Install it, or set RCD_PYTHON to its path." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "Node.js with npm is required to build the web app." >&2; exit 1; }

cd "${REPO}/apps/api"
[ -x .venv/bin/python ] || "${PYTHON}" -m venv .venv
.venv/bin/pip install -q -r requirements.lock.txt
.venv/bin/pip check
cd "${REPO}/apps/web"
npm ci --no-audit --no-fund
npm run build
