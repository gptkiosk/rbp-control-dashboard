# Secret and PII scan

Scanned 2026-10-11 over the working tree that will be published (the repository has no git history yet). `node_modules`, `apps/web/dist`, `__pycache__` and `.pytest_cache` were excluded because `.gitignore` keeps them out of the repository.

**Result: clean after redaction.** No credentials, private keys or tokens were found. Personal identifiers (a local username, machine hostname and absolute home-directory paths) were found in engineering records and removed. Re-scan after redaction: no matches.

## Limits of this scan

The repository's configured scanner, `gitleaks` with [`.gitleaks.toml`](../../.gitleaks.toml), and `trufflehog` are installed on the release host, but this run could not execute them because both needed an approval the run did not have. The scan below uses targeted `grep` patterns instead. **Run gitleaks before publishing:**

```sh
gitleaks dir . --config .gitleaks.toml --redact
```

Once the repository is initialised, also scan history with `gitleaks git .`.

## Credential patterns

| Pattern | Matches | Verdict |
| --- | --- | --- |
| OpenRouter `sk-or-` keys | Test fixtures only: `sk-or-test-*`, `sk-or-shared`, `sk-or-secret`, `sk-or-one`; one prefix check in `apps/api/openrouter_costs.py`; `OPENROUTER_API_KEY=rehearsal-not-a-secret` in `tests/zeroclaw/rehearsal.py` | Synthetic |
| GitHub `ghp_`, `github_pat_` | `apps/api/tests/test_mcp.py` fixtures (allowlisted in `.gitleaks.toml`); redaction regex in `apps/api/mcp.py`; prose in `CONTRIBUTING.md` | Synthetic |
| Google `AIza`, `GOCSPX-`, `*.apps.googleusercontent.com` | Redaction regex in `apps/api/mcp.py`; `test.apps.googleusercontent.com` in tests; placeholder in `docs/configuration/environment.md`; suffix check in `scripts/configure-google-auth.py` | Synthetic or code |
| Anthropic `sk-ant-`, AWS `AKIA`, Slack `xox?-`, Tailscale `tskey-`, PEM private keys | None | Clean |
| Secret-bearing files (`.env*`, `*.key`, `*.pem`, `*.token`, `*.db`, `*.sqlite*`, `client_secret*`, `credentials*.json`, SSH keys) | Only `apps/api/.env.example`, which contains placeholders | Clean |

## Personal data and host identifiers

| Finding | Files | Action |
| --- | --- | --- |
| Machine hostname in JUnit `hostname` attribute | 7 files in `docs/port/verification/*.xml` | Replaced with `build-host.local` |
| macOS temp path containing the local username | 3 of those XML files | Replaced with `/tmp/pytest-of-user` |
| Absolute checkout path containing the local username | `S2_existing_adapters-python.xml`, `S3_handoffs-python.xml` | Replaced with `/repo` |
| Absolute paths to the release host's workspace | `tests/adapter_conformance/VERIFICATION.md`, `docs/port/S3-routing-handoff.md` | Replaced with "the repository root" and `<mcd-checkout>` |
| VM guest home directory containing the local username | `docs/port/mcd-test-readiness.md` | Replaced with `/home/<user>.guest/` |

Checked and left in place:

- **Email addresses** are synthetic test values (`operator@example.com`, `stranger@gmail.com` as a rejected-login fixture) or project copyright text. No operator or contributor email address is present.
- **IP addresses** in `apps/api/tests/test_auth.py` and `test_agent_access.py` are private-range fixtures (`192.168.1.2`, `100.80.1.2`) used to test loopback-only access.
- **Tailnet names** are `example.ts.net` fixtures.
- **Discord IDs** are the synthetic values allowlisted in `.gitleaks.toml`.
- **`Bamcio LLC` and `GPT Kiosk`** appear in copyright notices and the inherited footer. They are intentional attribution.

## Screenshots

The 27 images in `docs/screenshots/` were captured on 2026-10-10 from an isolated MCD (macOS) preview, not RCD. RCD docs no longer link to them. They still sit in the folder pending removal, because the file move was not approved in this run. Two were re-inspected earlier (`overview-overview.png`, `projects-planning-map.png`), but they show the "Mac Control Dashboard" title and must not be published as RCD evidence. No RCD screenshot has been captured or scanned. See the [screenshot inventory](../screenshots/README.md).

These images still show MCD branding and Mac-specific views. Fresh RCD captures could not be produced in this run, because starting the isolated preview server needed an approval the run did not have.

## Other observations for the reviewer

- `docs/port/` holds engineering handoff notes that refer to internal story keys, run numbers and review findings. They contain no secrets or personal data after this redaction, but the operator may prefer to exclude or condense them before publishing.
