#!/usr/bin/env bash
# Render and (re)start the RCD systemd user service (Linux / Raspberry Pi OS). Counterpart of
# install-launchagent.sh on macOS. Restarting replaces the running service: do it when no
# jobs are running. Options are exported shell variables; none holds a credential.
set -euo pipefail

UNIT="${RCD_SYSTEMD_UNIT:-rcd-api}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${MAC_CONTROL_DATA_DIR:-${HOME}/.rcd-control}"
PYTHON_PATH="${MAC_CONTROL_PYTHON_PATH:-${REPO}/apps/api/.venv/bin/python}"
WORKING_DIRECTORY="${MAC_CONTROL_WORKING_DIRECTORY:-${REPO}/apps/api}"
SERVE_SCRIPT="${MAC_CONTROL_SERVE_SCRIPT:-serve.py}"
RESTART_SEC="${RCD_SYSTEMD_RESTART_SEC:-10}"
PORT="${MAC_CONTROL_PORT:-8800}"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
DEST="${UNIT_DIR}/${UNIT}.service"

[ "$(uname -s)" = "Linux" ] || { echo "this installer is for Linux; on macOS use scripts/install-launchagent.sh" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "systemctl not found: systemd is required" >&2; exit 1; }
[ -x "${PYTHON_PATH}" ] || { echo "missing Python executable: run scripts/bootstrap.sh or set MAC_CONTROL_PYTHON_PATH" >&2; exit 1; }
[ -f "${REPO}/apps/web/dist/index.html" ] || { echo "missing web build: run npm run build in apps/web" >&2; exit 1; }
case "${UNIT}" in *[!A-Za-z0-9_.@-]*|"") echo "invalid unit name: ${UNIT}" >&2; exit 1 ;; esac
case "${RESTART_SEC}${PORT}" in *[!0-9]*) echo "restart seconds and port must be numbers" >&2; exit 1 ;; esac
# A % starts a systemd specifier and a line break would add directives; the characters
# | & and backslash would corrupt the sed substitution. Reject them rather than escape.
for v in "${REPO}" "${DATA}" "${PYTHON_PATH}" "${WORKING_DIRECTORY}" "${SERVE_SCRIPT}"; do
  case "${v}" in
    *%*|*$'\n'*|*'|'*|*'&'*|*'\'*) echo "paths must not contain %, |, &, backslash or line breaks: ${v}" >&2; exit 1 ;;
  esac
done

mkdir -p "${DATA}" "${UNIT_DIR}"; chmod 700 "${DATA}"
sed -e "s|__WORKING_DIRECTORY__|${WORKING_DIRECTORY}|g" \
  -e "s|__DATA_DIR__|${DATA}|g" -e "s|__PYTHON_PATH__|${PYTHON_PATH}|g" \
  -e "s|__SERVE_SCRIPT__|${SERVE_SCRIPT}|g" -e "s|__RESTART_SEC__|${RESTART_SEC}|g" \
  "${REPO}/ops/systemd/rcd-api.service.template" > "${DEST}.tmp"
if grep -q '__[A-Z_]*__' "${DEST}.tmp"; then rm -f "${DEST}.tmp"; echo "unrendered placeholder in unit" >&2; exit 1; fi
if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze --user verify "${DEST}.tmp" >/dev/null 2>&1 || echo "note: systemd-analyze reported warnings for the unit" >&2
fi
chmod 600 "${DEST}.tmp"
mv "${DEST}.tmp" "${DEST}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}.service"
systemctl --user restart "${UNIT}.service"
# Without lingering the user service stops at logout and does not start at boot.
if command -v loginctl >/dev/null 2>&1 && [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "note: run 'sudo loginctl enable-linger $(id -un)' so the service starts at boot and survives logout" >&2
fi

for _ in $(seq 1 20); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    echo "started ${UNIT}.service; healthz OK"
    exit 0
  fi
  sleep 0.5
done
echo "started ${UNIT}.service but healthz did not answer within 10 s; run: journalctl --user -u ${UNIT} -n 50" >&2
exit 1
