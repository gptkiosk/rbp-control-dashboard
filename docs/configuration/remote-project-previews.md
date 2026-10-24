# Remote project preview access

## Purpose

Project previews remain bound to `127.0.0.1`. They are never exposed directly to a LAN, a public address, or Tailscale Serve/Funnel. An operator who needs to inspect a Pi or Mac-hosted preview from another Tailscale device uses SSH local-port forwarding.

## Reserved preview port group

Use ports **41350–41399** for temporary project review previews. A project normally prefers:

```text
41350 + project ID
```

For example, project 2 prefers port `41352`. A preview script must first confirm that its preferred port is free. If it is occupied, it chooses the next free port inside this range, records the actual port in `.preview/preview.state`, and never stops the existing listener. The state file is authoritative; do not guess the active port from a past verifier result.

Project preview scripts should accept `PREVIEW_PORT` so an operator can select the preferred port explicitly:

```sh
PREVIEW_PORT=41352 bash tools/verify-preview.sh serve
```

They must bind only to `127.0.0.1`, print the actual port and source SHA, write the same values to `.preview/preview.state`, and leave a persistent review preview running only for the human approval interval. One-shot `verify` runs may choose another free port and must stop their own process when finished; their saved URL list is evidence for that one-shot run, not the address of a later `serve` process.

## Remote review through Tailscale SSH

From a Tailscale-connected review machine, forward the recorded loopback port without changing any Tailscale Serve mapping or opening a firewall port:

```sh
ssh -N -o ExitOnForwardFailure=yes -L <PORT>:127.0.0.1:<PORT> <USER>@<TAILNET-HOST>
```

Then open `http://127.0.0.1:<PORT>/` on the review machine. Keep the SSH terminal open during the review. This makes the port reachable only through the authenticated SSH session; it does not publish the preview to the tailnet.

## Required preview handoff

Every human or CI preview-review story records:

1. project ID, preferred port and actual port;
2. source commit and the complete state-file contents;
3. exact `serve` and `stop` commands;
4. the local clickable page URLs using the **actual** running port;
5. the SSH forwarding command with `<USER>` and `<TAILNET-HOST>` left as operator-provided placeholders;
6. the verifier evidence directory and whether screenshots were captured; and
7. confirmation that `stop` removed only this preview’s PID/state after approval.

Do not reuse a one-shot verifier's stale port when composing a persistent preview handoff. If the preferred port was unavailable, report the fallback instead of evicting another process.
