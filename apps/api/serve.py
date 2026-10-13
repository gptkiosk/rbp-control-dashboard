"""Run the API with host and port from settings (single source of truth).

Used by the LaunchAgent and by `scripts/run.sh`. Refuses a non-loopback bind
until auth exists, so a stray MAC_CONTROL_HOST cannot expose the dashboard.
"""

from __future__ import annotations

import ipaddress
import sys

import uvicorn

from settings import get_settings


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> int:
    settings = get_settings()
    if not _is_loopback(settings.host) and not settings.auth_enabled:
        print(
            f"refusing to bind {settings.host}: Google sign-in is not enabled.",
            file=sys.stderr,
        )
        return 2
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        proxy_headers=False,
        access_log=False,  # OAuth callback queries contain one-time codes.
        # Open live-status streams never finish on their own; without a limit a restart
        # (systemctl restart) would wait for every browser tab to go away.
        timeout_graceful_shutdown=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
