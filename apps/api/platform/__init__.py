"""Host-specific collectors selected at runtime.

The public API and database use one metric schema.  Platforms only supply the
host-specific ways of obtaining those values.
"""

from __future__ import annotations

# This project historically imports API modules as loose modules, putting this
# directory at the front of sys.path.  Preserve the stdlib ``platform`` API for
# dependencies which import it while exposing the host collector package.
import importlib.util
import sys
import sysconfig
from pathlib import Path

_stdlib_platform = Path(sysconfig.get_path("stdlib")) / "platform.py"
_spec = importlib.util.spec_from_file_location("_rcd_stdlib_platform", _stdlib_platform)
if _spec and _spec.loader:  # pragma: no branch - present on supported CPython builds
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    for _name in dir(_module):
        if not _name.startswith("__"):
            globals().setdefault(_name, getattr(_module, _name))

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
