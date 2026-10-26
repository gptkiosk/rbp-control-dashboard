# Standard UI preview and sign-off

For every story that changes a user interface, provide the reviewer a reachable isolated preview as part of the handoff. Do not merely report that a build passed.

Record:

- Exact loopback URL/port and access method, source revision or snapshot, and start/stop commands.
- Separate private test data directory and synthetic accounts/reports/projects. Never copy production databases or credential files.
- Which collector, dispatcher, alerts, external APIs and native runtimes are enabled. Keep execution/provider delivery disabled unless explicitly needed and authorized.
- UI paths/flows tested, meaningful screenshot evidence, known gaps, and whether tests use fixtures, an ARM64 VM or physical hardware.

Check that the chosen port is unused. Never stop or reconfigure another service found by port lookup. Preserve live production dashboards and active jobs. Keep unauthenticated previews on loopback; remote access requires a reviewed authenticated/private route, not a public bind or auth bypass.

Mac and Linux/Pi are separate targets. A temporary Linux ARM64 VM can verify Linux code and UI paths but cannot certify Raspberry Pi OS, GPIO, temperature/throttling or physical-Pi memory/performance. After app testing, explicit operator sign-off and public publication, preserve source/receipts outside the VM and retire temporary previews/VMs. An absent retired preview is normal; bring up a fresh environment only for further requested testing.

The existing report-root settings are MAC_CONTROL_OPS_REPORTS_DIR and MAC_CONTROL_HERMES_REPORTS_DIR. Configure the preview to a synthetic report folder, rather than exposing production reports. A follow-up story adds a clearer install/UI configuration workflow and tests custom runtime-directory defaults for both apps.


## 0.3.0 release fixture preview

Start from the repository root with the API Python:

```sh
python3 scripts/preview-release-features.py --port PORT --data-dir /tmp/PRODUCT-resume/synthetic-release-preview
```

Use port 8813 for MCD and 8814 for RCD (replace PRODUCT with mcd or rcd). Check the port is free first. Open http://127.0.0.1:8813/profile#agent-roles or http://127.0.0.1:8814/profile#agent-tools. Stop the foreground process with Ctrl-C; for a background process record and terminate only its own PID.

This preview serves the current built UI and synthetic accounts, tools, update notices and role assignments. Installer and role previews are read-only; every apply/install/update/rollback action is refused. No collectors, dispatchers, provider calls, native account reads, delivery or real service changes are enabled. Use a fresh build after source changes. Screenshots of these fixtures are evidence of controls and layout, not account or hardware readiness.

## 0.6.69 planning activity preview

The paired web builds render the same `ProjectPlanningProgress` component from existing project pipeline/task state. Review the prominent heading, three stages, task link, queued retry precedence, approval/recovery/ready states and 390px stacked layout. Reduced motion disables the spinner animation. The display adds no prompt fields, model calls or polling.

Implementation preview: `http://127.0.0.1:8900/projects?project=67`, synthetic project 67 only, source `codex/planning-progress` based on v0.6.68 (the signed package names the final merged commit). Start: `/tmp/codex-pipeline-067-venv/bin/python /tmp/069-planning-preview.py --port 8900 --data-dir /tmp/coordinator-069-planning/synthetic-release-preview`. The recorded fixture process is PID 11356; stop only that process after checking its script identity. All mutation routes, dispatchers, native runtimes and provider delivery are disabled. No live project state or secrets were imported. This temporary fixture uses the RCD build on a Mac; paired source/type builds and CI establish MCD coverage, not physical Pi or live planning/provider acceptance.
