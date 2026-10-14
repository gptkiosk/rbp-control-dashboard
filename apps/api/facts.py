"""Slow-changing facts: Tailscale status and pending macOS updates (read-only)."""

from __future__ import annotations

import json
import re


def parse_tailscale(text: str) -> dict[str, object]:
    data = json.loads(text)
    me = data.get("Self") or {}
    peers = []
    for p in (data.get("Peer") or {}).values():
        peers.append(
            {
                "hostname": p.get("HostName"),
                "dns_name": p.get("DNSName"),
                "os": p.get("OS"),
                "online": bool(p.get("Online")),
                "active": bool(p.get("Active")),
                "relay": p.get("Relay") or None,
                "direct_addr": p.get("CurAddr") or None,
                "last_seen": p.get("LastSeen"),
                "ips": p.get("TailscaleIPs") or [],
            }
        )
    peers.sort(key=lambda p: (not p["online"], str(p["hostname"]).lower()))
    return {
        "backend_state": data.get("BackendState"),
        "version": data.get("Version"),
        "tailnet": (data.get("CurrentTailnet") or {}).get("Name"),
        "magic_dns_suffix": data.get("MagicDNSSuffix"),
        "self": {
            "hostname": me.get("HostName"),
            "dns_name": me.get("DNSName"),
            "ips": me.get("TailscaleIPs") or [],
            "online": bool(me.get("Online")),
        },
        "peers": peers,
    }


_UPDATE_TITLE_RE = re.compile(
    r"Title:\s*(?P<title>[^,]+),\s*Version:\s*(?P<version>[^,]+),.*?"
    r"Recommended:\s*(?P<rec>YES|NO)(?:,\s*Action:\s*(?P<action>[^,]+))?",
)


def parse_softwareupdate(text: str) -> list[dict[str, object]]:
    """Updates from `softwareupdate -l`. An empty list means none pending."""
    updates: list[dict[str, object]] = []
    label: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("* Label:"):
            label = stripped.split(":", 1)[1].strip()
            continue
        m = _UPDATE_TITLE_RE.search(stripped)
        if m:
            updates.append(
                {
                    "label": label,
                    "title": m.group("title").strip(),
                    "version": m.group("version").strip(),
                    "recommended": m.group("rec") == "YES",
                    "requires_restart": (m.group("action") or "").strip().lower() == "restart",
                }
            )
            label = None
    return updates


def parse_apt_updates(text: str) -> list[dict[str, object]]:
    """Parse ``apt list --upgradable`` without treating its status line as a package."""
    updates: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line or line.startswith("Listing...") or "/" not in line:
            continue
        package, _, rest = line.partition("/")
        channel, _, version = rest.partition(" ")
        if package and channel and version:
            updates.append({"label": package, "title": package, "version": version.strip().split()[0],
                            "recommended": True, "requires_restart": False})
    return updates
