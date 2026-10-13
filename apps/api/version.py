"""Release identification for the mac-control API."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

__version__ = "0.2.0"


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


@lru_cache(maxsize=1)
def git_dirty() -> bool:
    """True when tracked files differ from the commit, so a running build can be told from the commit it names."""
    repo = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.stdout.strip())
