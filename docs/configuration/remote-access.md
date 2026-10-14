# Remote access from an iPhone

## Purpose

Reach MCD through your private Tailscale network using HTTPS and Google sign-in. Keep MCD bound to `127.0.0.1` even after enabling authentication; the Tailscale proxy supplies remote access. This workflow does not require public internet exposure.

## Screenshots

Pending capture: `profile-settings.png` (responsive profile view). No RCD capture exists yet. Captures never prove a phone connection or a real tailnet identity.

## Controls

1. Confirm MCD responds locally at `http://127.0.0.1:8800/healthz` with status OK and configure [Google sign-in](google-sign-in.md).
2. Choose an available Tailscale HTTPS port. Port 9443 is an example; inspect existing Serve mappings so another service is not replaced.
3. Register the exact HTTPS callback in Google and include its origin in MCD’s private auth configuration.
4. Configure an existing Tailscale installation to proxy the loopback server. Example command, to review for your installation:

```sh
tailscale serve --bg --https=9443 http://127.0.0.1:8800
```

5. On iPhone, connect the Tailscale app to the authorized tailnet. Open `https://<HOSTNAME>:9443` in Safari and sign in with an allowlisted Google account. Use the hostname/port actually configured on the Mac.
6. Verify anonymous **data API** access is refused and signed-in access works. The login shell/assets and `/healthz` are public exceptions; a page returning 200 does not by itself mean data is exposed.

Use Serve within the tailnet, not a public publishing/Funnel route. Tailnet membership and network access policy still determine which devices can connect.

## Settings involved

```ini
MAC_CONTROL_HOST=127.0.0.1
MAC_CONTROL_PORT=8800
MAC_CONTROL_AUTH_ENABLED=true
MAC_CONTROL_AUTH_ORIGINS='["http://127.0.0.1:8800","https://<HOSTNAME>:9443"]'
```

Replace the hostname placeholder privately. Complete OAuth credentials and the email allowlist are also required. Origins contain no path; the Google redirect URI includes `/auth/callback`. Array values use JSON, not Python tuple syntax.

Tailscale routing is configured separately from MCD. No Tailscale enrollment key is required in the dashboard profile. Appearance can follow the device or a saved Light/Dark preference. Phone views use responsive controls and scrollable wide tables.

## Secret placeholders

Use `<HOSTNAME>` for a private tailnet name and example emails for operators. Keep real device identities, OAuth secrets and enrollment credentials out of public screenshots.

## Troubleshooting

- **Cannot connect:** check the phone’s tailnet connection/policy, the Mac’s Serve mapping, and local MCD health. Keep the loopback bind; do not solve this by exposing the server to the LAN.
- **Callback mismatch:** the registered redirect must exactly match scheme, hostname, port and `/auth/callback`. Update the private MCD origins and reload configuration as needed.
- **Login works but profile does not:** use Google sign-in; local recovery is restricted to direct loopback and does not supply a Google profile identity.
- **Anonymous API data accessible:** check auth configuration and the specific endpoint. Public health/login/static endpoints are intentionally different from protected dashboard data.
- **Narrow screen:** scroll tables within their panel; open the mobile menu for navigation. Check dialog actions remain reachable.

## Related pages

- [Google sign-in](google-sign-in.md), [environment](environment.md).
- [Settings](settings.md), [LaunchAgent](launchd.md).
