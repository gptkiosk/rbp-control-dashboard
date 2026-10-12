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
