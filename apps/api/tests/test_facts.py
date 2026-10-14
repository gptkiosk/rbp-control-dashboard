from __future__ import annotations

import json

import facts

TAILSCALE = json.dumps({
    "BackendState": "Running", "Version": "1.98.9", "MagicDNSSuffix": "example.ts.net",
    "CurrentTailnet": {"Name": "operator@example.com"},
    "Self": {"HostName": "example-mac", "DNSName": "example-mac.example.ts.net.",
             "TailscaleIPs": ["198.51.100.109"], "Online": True},
    "Peer": {
        "a": {"HostName": "laptop", "OS": "macOS", "Online": True, "Active": True,
              "CurAddr": "192.0.2.57:41641", "Relay": "", "TailscaleIPs": ["203.0.113.68"]},
        "b": {"HostName": "Phone", "OS": "iOS", "Online": False, "Active": False},
    },
})

SOFTWAREUPDATE = """Software Update Tool

Finding available software
Software Update found the following new or updated software:
* Label: macOS Tahoe 26.6.2-25G83
\tTitle: macOS Tahoe 26.6.2, Version: 26.6.2, Size: 3833693KiB, Recommended: YES, Action: restart,
"""


def test_tailscale_parse_sorts_online_peers_first():
    t = facts.parse_tailscale(TAILSCALE)
    assert t["backend_state"] == "Running"
    assert t["self"]["ips"] == ["198.51.100.109"]
    assert [p["hostname"] for p in t["peers"]] == ["laptop", "Phone"]
    assert t["peers"][0]["direct_addr"] == "192.0.2.57:41641"
    assert t["peers"][0]["relay"] is None


def test_softwareupdate_parse():
    u = facts.parse_softwareupdate(SOFTWAREUPDATE)
    assert u == [{
        "label": "macOS Tahoe 26.6.2-25G83", "title": "macOS Tahoe 26.6.2",
        "version": "26.6.2", "recommended": True, "requires_restart": True,
    }]


def test_softwareupdate_none_pending():
    assert facts.parse_softwareupdate("Software Update Tool\n\nNo new software available.\n") == []


def test_apt_upgrades_parse_without_the_listing_banner():
    assert facts.parse_apt_updates("Listing...\nopenssl/stable 3.0.17-1 arm64 [upgradable from: 3.0.16-1]\n") == [{
        "label": "openssl", "title": "openssl", "version": "3.0.17-1",
        "recommended": True, "requires_restart": False,
    }]
