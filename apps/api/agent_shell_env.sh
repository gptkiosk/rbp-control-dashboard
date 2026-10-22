#!/bin/sh
# Codex's shell tool runs commands through `bash -lc`. Login profiles may
# replace PATH, so restore the dashboard-owned agent tools after they load.
if [ -n "${DASHBOARD_AGENT_RUNTIME_PATH:-}" ]; then
    export PATH="${DASHBOARD_AGENT_RUNTIME_PATH}${PATH:+:${PATH}}"
fi
