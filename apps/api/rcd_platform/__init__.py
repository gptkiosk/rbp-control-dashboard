"""Host-specific collectors selected at runtime.

The public API and database use one metric schema.  Platforms only supply the
host-specific ways of obtaining those values.
"""

from __future__ import annotations

import sys

from .base import Platform
from .linux import LinuxPlatform
from .macos import MacOSPlatform


def current_platform(**kwargs) -> Platform:
    """Create the supported platform implementation for this interpreter."""
    if sys.platform == "darwin":
        return MacOSPlatform(**kwargs)
    if sys.platform.startswith("linux"):
        return LinuxPlatform(**kwargs)
    raise RuntimeError(f"unsupported host platform: {sys.platform}")


__all__ = ("Platform", "LinuxPlatform", "MacOSPlatform", "current_platform")
