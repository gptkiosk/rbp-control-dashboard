# Reconciled 0.3.0 candidate preview

Preview URL: `http://127.0.0.1:8814/profile#agent-tools`. It serves the built application with synthetic read-only responses. No production database, native account files, collector, dispatcher, alerts, provider calls, GitHub network access or install helper is connected. Only the read-only tool plan endpoint accepts POST; every actual mutation is refused. A synthetic fixture identity is displayed by this separate preview app; it is not a login to a real dashboard.

Start after `npm run build` in `apps/web`:

```sh
python3 scripts/preview-release-features.py --port 8814 --data-dir /tmp/rcd-resume/synthetic-release-preview
```

Use the API venv Python. Keep the terminal open; Ctrl+C stops this preview only. The script binds exclusively to loopback. Do not point it at native dashboard data or install it as a service.

Source: `codex/rcd-resume-20261013`, with version 0.3.0 candidate changes. Final source SHA is recorded in the repository commit and the external punchlist. Initial screenshot source was 248aef7 plus the candidate version/docs changes. Evidence was captured on 2026-10-13 in a desktop browser, with synthetic data.

Checked visually: four tool versions, install confirmation, commands, sources/hashes, disk/memory and unchecked confirmation preventing install. Unit tests cover the mutation refusal and helper workflows with synthetic hosts. This preview does not prove a packaged install, a signed GitHub download, a vendor login or physical Raspberry Pi operation.
