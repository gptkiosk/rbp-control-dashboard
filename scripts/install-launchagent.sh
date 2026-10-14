#!/usr/bin/env bash
# Render and (re)load the mac-control LaunchAgent. Uses bootout then bootstrap so
# launchd re-reads the plist (kickstart would keep the old definition).
set -euo pipefail

LABEL="${MAC_CONTROL_LAUNCHD_LABEL:-com.operator.rcd-control}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${MAC_CONTROL_DATA_DIR:-${HOME}/.rcd-control}"
DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
PYTHON_PATH="${MAC_CONTROL_PYTHON_PATH:-${REPO}/apps/api/.venv/bin/python}"
WORKING_DIRECTORY="${MAC_CONTROL_WORKING_DIRECTORY:-${REPO}/apps/api}"
SERVE_SCRIPT="${MAC_CONTROL_SERVE_SCRIPT:-serve.py}"
PYTHONUNBUFFERED_VALUE="${MAC_CONTROL_PYTHONUNBUFFERED:-1}"
RUN_AT_LOAD="${MAC_CONTROL_RUN_AT_LOAD:-true}"
KEEP_ALIVE_SUCCESSFUL_EXIT="${MAC_CONTROL_KEEP_ALIVE_SUCCESSFUL_EXIT:-false}"
THROTTLE_INTERVAL="${MAC_CONTROL_THROTTLE_INTERVAL:-60}"
STDOUT_PATH="${MAC_CONTROL_STDOUT_PATH:-${DATA}/logs/api.out.log}"
STDERR_PATH="${MAC_CONTROL_STDERR_PATH:-${DATA}/logs/api.err.log}"

[ -x "${PYTHON_PATH}" ] || { echo "missing Python executable: run scripts/bootstrap.sh or set MAC_CONTROL_PYTHON_PATH" >&2; exit 1; }
[ -f "${REPO}/apps/web/dist/index.html" ] || { echo "missing web build: run npm run build in apps/web" >&2; exit 1; }

mkdir -p "${DATA}/logs"; chmod 700 "${DATA}"
sed -e "s#__LABEL__#${LABEL}#g" -e "s#__PYTHON_PATH__#${PYTHON_PATH}#g" \
  -e "s#__SERVE_SCRIPT__#${SERVE_SCRIPT}#g" -e "s#__WORKING_DIRECTORY__#${WORKING_DIRECTORY}#g" \
  -e "s#__PATH__#${PATH}#g" -e "s#__PYTHONUNBUFFERED__#${PYTHONUNBUFFERED_VALUE}#g" \
  -e "s#__RUN_AT_LOAD__#<${RUN_AT_LOAD}/>#g" -e "s#__KEEP_ALIVE_SUCCESSFUL_EXIT__#<${KEEP_ALIVE_SUCCESSFUL_EXIT}/>#g" \
  -e "s#__THROTTLE_INTERVAL__#${THROTTLE_INTERVAL}#g" -e "s#__STDOUT_PATH__#${STDOUT_PATH}#g" \
  -e "s#__STDERR_PATH__#${STDERR_PATH}#g" \
  "${REPO}/ops/launchd/com.operator.mac-control.plist.template" > "${DEST}.tmp"
# Persist only host installation/report settings; no credential values are copied.
# plistlib escapes local folder names correctly, including spaces and XML characters.
"${PYTHON_PATH}" - "${DEST}.tmp" "${DATA}" <<'PYCONFIG'
import os
import plistlib
import sys
path, data = sys.argv[1:]
with open(path, "rb") as file:
    config = plistlib.load(file)
values = config["EnvironmentVariables"]
values["MAC_CONTROL_DATA_DIR"] = data
for name in ("MAC_CONTROL_OPS_REPORTS_DIR", "MAC_CONTROL_HERMES_REPORTS_DIR",
             "MAC_CONTROL_REPORTS_ALLOWED_ROOTS"):
    if name in os.environ:
        values[name] = os.environ[name]
with open(path, "wb") as file:
    plistlib.dump(config, file)
PYCONFIG
plutil -lint "${DEST}.tmp" >/dev/null
mv "${DEST}.tmp" "${DEST}"

# bootout returns before launchd finishes tearing the job down; bootstrapping during
# teardown fails with "5: Input/output error". Wait until the job is gone (max 45 s, including an in-flight alert send).
if launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
  for _ in $(seq 1 90); do
    launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1 || break
    sleep 0.5
  done
fi

# One retry covers a late teardown; a second failure is a real error.
if ! launchctl bootstrap "${DOMAIN}" "${DEST}" 2>/dev/null; then
  sleep 2
  launchctl bootstrap "${DOMAIN}" "${DEST}"
fi

# Confirm the job is loaded and answering before reporting success.
for _ in $(seq 1 20); do
  if curl -fsS --max-time 2 "http://127.0.0.1:8800/healthz" >/dev/null 2>&1; then
    echo "loaded ${LABEL}; healthz OK"
    exit 0
  fi
  sleep 0.5
done
echo "loaded ${LABEL} but healthz did not answer within 10 s; check ${DATA}/logs/api.err.log" >&2
exit 1
