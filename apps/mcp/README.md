# MCD tool server

Stdio MCP server for Hermes, with operator-approved expiring Read or Read + planning drafts
access. It lists tasks and limited agent metadata. Draft access creates Backlog tasks and edits
Hermes's own Backlog drafts, including definition of done and dependencies. Operator actions
queue work, change statuses and approve tasks. Queue/status requests are refused.

Register through the separately approved dashboard MCP change. Default credential file:
~/.mac-control/agent-tokens/hermes.token (mode 600). No secret is passed through arguments or
returned by the dashboard. MCD_URL defaults to http://127.0.0.1:8800; explicit loopback IPs only.
MCD_TOKEN_FILE can select an isolated test file. No proxy or redirect receives the credential.
Never use the admin recovery token or an operator browser cookie.

See ../../docs/HERMES_ACCESS.md for grant/revocation behavior and security boundaries.

    .venv/bin/python mcd_server.py            # stdio; normally started by Hermes
    .venv/bin/python -m pytest -q tests       # unit tests, no model invocation
