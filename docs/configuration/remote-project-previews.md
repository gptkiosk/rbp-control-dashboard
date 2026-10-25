# Remote project preview access

## Purpose

A remote operator never needs a shell on the RCD or MCD host to review a project preview. The dashboard owns the preview controls, captures the host-side transcript, and opens the running preview through its authenticated preview proxy.

Project previews remain bound to `127.0.0.1`. They are never exposed directly to a LAN, public address, Tailscale Serve/Funnel, or a dashboard listener other than the authenticated proxy route.

## Reserved preview port group

Use ports **41350–41399** for temporary project review previews. A project normally prefers `41350 + project ID`; project 2 therefore prefers `41352`. A script confirms the preferred port is free, otherwise uses the next free reserved port and records the actual value in `.preview/preview.state`. It never stops another listener.

The state file is authoritative. It holds the preview PID, actual loopback port, source SHA and start time. One-shot verification evidence may name a different port; it is never reused as the address of a later persistent preview.

## Dashboard preview controls

A reviewed preview plan has two finite host actions:

- `preview-verify` runs `tools/verify-preview.sh verify` once on the dashboard host. Its output is shown in the task, stored in the project ledger, and becomes a reviewable host-verification receipt for an agent story.
- `preview-review` offers **Start preview on host**, **Open remote preview**, and **Stop preview**. Start runs only `tools/verify-preview.sh serve`; Stop runs only its `stop` action. The task shows the command transcript, PID, port and SHA.

The API accepts no arbitrary shell command or path. It resolves the script from the approved project workspace and accepts only these three action words. The preview proxy reads only that state file, connects only to `127.0.0.1` on the recorded reserved port, and serves static preview content only to an authenticated dashboard operator.

## Required preview handoff

Every preview review records the project ID, actual port, source SHA, state-file values, verifier transcript, screenshot evidence, and the final stop outcome. The operator reviews the proxy URL in desktop and mobile states, then records their decision. No terminal command is part of the operator workflow.
