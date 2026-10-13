# Google sign-in

## Purpose

Google sign-in restricts MCD to explicitly allowlisted operators. The authorization-code flow uses PKCE, state, a browser-binding cookie and nonce with `openid email` scope. It does not connect Gmail or Drive or retain Google API access/refresh tokens.

## Screenshots

Pending capture: `profile-settings-account.png`. A capture would show Settings layout only, not a Google login or sign-out. Sign-in configuration is host-level, separate from profile preferences.

## Controls

Create a Google **Web application** OAuth client and register each exact callback URL. For the default local installation, register `http://127.0.0.1:8800/auth/callback`. For private remote access, register `https://<PRIVATE_HOSTNAME>:<HTTPS_PORT>/auth/callback` using your own configured HTTPS address.

For a personal Gmail operator, the OAuth audience must allow external users; Google generally limits testing apps to listed test users, but exempts sign-in-only requests for basic identity scopes such as MCD’s `openid email`. An internal-only audience excludes personal Gmail accounts. This Google audience setting does not replace MCD's own email allowlist. See [Google’s audience documentation](https://support.google.com/cloud/answer/15549945?hl=en).

Keep the downloaded JSON private. The import helper can configure the host:

```sh
apps/api/.venv/bin/python scripts/configure-google-auth.py \
  ~/.mac-control/google-oauth-client.json \
  --enable --allowed-email operator@example.com
```

Replace the example email and source path with your own. The helper requires an owned regular source file, refuses symlinks, bounds its size and sets its permissions to `600`. It validates the web-client credentials and local callback, extracts valid HTTPS callback origins, preserves other dotenv settings and privately backs up an existing dotenv file before replacement. `--data-dir` selects the helper's output directory; the application's default dotenv lookup remains `~/.mac-control/.env`, so coordinate any custom location explicitly. Without `--enable`, the helper writes auth disabled.

Restart the application after changing host settings. The LaunchAgent installer performs a reload, interrupting active runs; wait for a safe time. The installer does not load dotenv values itself: the application loads them at startup.

## Settings involved

| Key | Default | Purpose |
|---|---|---|
| `MAC_CONTROL_AUTH_ENABLED` | `false` | Enables sign-in; startup requires complete auth configuration. |
| `MAC_CONTROL_GOOGLE_CLIENT_ID` | empty | Web OAuth client identifier. |
| `MAC_CONTROL_GOOGLE_CLIENT_SECRET` | empty | Private client secret. |
| `MAC_CONTROL_AUTH_ALLOWED_EMAILS` | `[]` | Explicit operator email allowlist. |
| `MAC_CONTROL_AUTH_ORIGINS` | `["http://127.0.0.1:8800"]` | Canonical loopback HTTP or HTTPS origins, without a path, credentials, query or fragment. |

Use JSON arrays for list values in dotenv, not Python tuple syntax:

```dotenv
MAC_CONTROL_AUTH_ENABLED=true
MAC_CONTROL_GOOGLE_CLIENT_ID=<CLIENT_ID>
MAC_CONTROL_GOOGLE_CLIENT_SECRET=<SECRET>
MAC_CONTROL_AUTH_ALLOWED_EMAILS=["operator@example.com"]
MAC_CONTROL_AUTH_ORIGINS=["http://127.0.0.1:8800","https://<PRIVATE_HOSTNAME>:<HTTPS_PORT>"]
```

The origin omits `/auth/callback`; the registered Google redirect URL includes it. Google requires the full callback URL to match exactly.

Sessions last 12 hours. MCD stores a session-token hash in the singular `auth_session` table, with identity, origin and expiry. Cookies are `HttpOnly` and `SameSite=Lax`; HTTPS uses a `Secure`, `__Host-` cookie. Logout revokes the session. Removing a Google user from the MCD allowlist refuses their next authenticated request.

### Local recovery and public routes

When auth is enabled, the server creates `<DATA_DIR>/admin-recovery-token` if absent and enforces private ownership and mode `600`. Use **Local administrator recovery** at the direct local address only. Remote/proxied recovery is refused, and attempts are rate-limited. Recovery creates a revocable local administrator session; keep the token private.

Login/status/callback/recovery routes, health and necessary static assets are intentionally public: `/login`, `/auth/status`, `/auth/login`, `/auth/callback`, `/auth/recover`, `/healthz` and the application icons/assets. Protected pages redirect browsers to login; anonymous protected data API requests return `401`. A successful health or login-page response is not an authentication failure.

## Secret placeholders

Keep the secret, downloaded JSON, recovery token and dotenv backups outside source control. Use `<CLIENT_ID>`, `<SECRET>`, example emails and `<PRIVATE_HOSTNAME>` in public material. Client identifiers are not passwords, but installation-specific identifiers should still be replaced in distribution examples.

## Troubleshooting

- **`org_internal`:** change the Google consent audience to allow the intended personal account; separately verify MCD’s own allowlist.
- **Redirect mismatch:** compare the exact callback scheme, hostname, port and path with Google registration. Also configure its origin in MCD and restart safely.
- **State or nonce failure:** the login flow expires after five minutes and is used once. A server restart invalidates in-progress login; begin again.
- **Recovery refused:** use the direct local login screen without a proxy. Do not expose or paste the recovery token remotely.
- **Access verification:** test a protected endpoint such as `/api/cards` without a session, then sign in from the intended device. Keep the backend bound to loopback for the documented Tailscale deployment.

## Related pages

- [Private iPhone and Tailscale access](remote-access.md)
- [Environment reference](environment.md)
- [LaunchAgent reload](launchd.md)
- [Runtime data and backups](runtime-data.md)
