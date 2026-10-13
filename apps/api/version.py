"""Release identification for the mac-control API."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

__version__ = "0.1.0"


@lru_cache(maxsize=1)
def git_sha() -> str:
    """Short git SHA of the checkout, or "unknown" outside a git work tree."""
    repo = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"
