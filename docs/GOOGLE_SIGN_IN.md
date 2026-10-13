# Google sign-in

MCD uses Google's authorization-code flow with PKCE, state, a browser-binding cookie
and nonce. Only `openid email` is requested. Signed ID tokens must match Google's
issuer, this client, the nonce, expiry and a verified allowlisted email. No Google API
access/refresh tokens are retained. This sign-in does not connect Gmail or Drive.

Create a **Web application** client for Mac Control Dashboard. Configure the local callback
and your canonical HTTPS callback:

```
http://127.0.0.1:8800/auth/callback
https://<PRIVATE_HOSTNAME>:<HTTPS_PORT>/auth/callback
```

JavaScript origins can remain empty. Port 443 serves OpenClaw and 8443 retains its
existing proxy. Mission Control’s 3443 proxy was retired on October 9, 2026.
MCD uses a separate 9443 listener.
Non-loopback callbacks require HTTPS; raw LAN HTTP/IP callbacks are not supported
by Google. Register and configure any other canonical HTTPS address explicitly.

Configure `MAC_CONTROL_AUTH_ALLOWED_EMAILS` with your approved accounts. When the Google
consent screen is External/Testing, add those accounts as test users in Audience.

Download the client JSON to `~/.mac-control/google-oauth-client.json`. Import it:

```sh
apps/api/.venv/bin/python scripts/configure-google-auth.py \
  ~/.mac-control/google-oauth-client.json --enable
./scripts/install-launchagent.sh
```

Without `--enable`, importing leaves sign-in disabled. The importer requires the
local callback and uses the tailnet address only when it is in the JSON. It preserves
other settings and saves private `.env.before-google-auth-*` backups. Credentials,
JSON and backups stay outside Git, owned by the Mac user, mode 600; directory 700.
Import errors never display credential values. If callbacks are edited after the
download, download updated JSON or update `MAC_CONTROL_AUTH_ORIGINS` to match the
registered addresses. Keep `MAC_CONTROL_HOST=127.0.0.1` for Tailscale Serve.

## Sessions and local recovery

Sessions last 12 hours. Cookies are HttpOnly, SameSite=Lax and origin-bound; HTTPS
uses Secure `__Host-` cookies. SQLite stores only token hashes. Logout revokes the
session; expiration or removal from the allowlist refuses it. All data/action routes
require a session when enabled. Public exceptions are health, the login page,
login/bootstrap/recovery endpoints and static assets needed to show the login page.
The existing custom write header and Origin checks remain required.

`~/.mac-control/admin-recovery-token` is generated when sign-in first starts, mode
600. Use it through **Local administrator recovery** at the direct local address.
Recovery is refused remotely and through forwarded headers; attempts are limited.
It grants a revocable local administrator session. Keep this file private and out of
agent configuration. Recovery, cookie expiry and revocation are covered by tests.

OAuth state expires after five minutes and is consumed once. Restarting during a
login cancels that attempt; start again. Use `serve.py` so access logs cannot capture
OAuth codes and forwarded headers cannot override the configured address.

## Tailnet and validation

After authentication is enabled and the 9443 origin is configured:

```sh
/usr/local/bin/tailscale serve --bg --https=9443 http://127.0.0.1:8800
```

Use Serve within the tailnet. Preserve the existing proxies. Confirm anonymous data
returns 401 and signed-in access works from a second tailnet device. Google sign-in
with the actual accounts and a second device require operator verification; mocked
OIDC tests and recovery checks do not establish that result.

Hermes MCD MCP uses a separate expiring, revocable loopback capability, approved in the
MCP Agent access panel. It never receives an operator cookie or recovery token. See
[HERMES_ACCESS.md](HERMES_ACCESS.md) for read/draft scopes and separate MCP registration
approval. Installing this support creates no live grant automatically. Browser chats and
agent monitoring continue after an operator signs in.

References: [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect),
[Google web OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).
