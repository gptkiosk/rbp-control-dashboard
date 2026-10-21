"""Release identification for the mac-control API."""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

__version__ = "0.6.47"


def _build_info(repo: Path) -> dict:
    """The identity a release package records at build time (BUILD_INFO.json), for installs with no .git."""
    try:
        data = json.loads((repo / "BUILD_INFO.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def git_sha() -> str:
    """Short git SHA of the checkout, or of the release package's source commit, or "unknown"."""
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
        commit = str(_build_info(repo).get("source_commit") or "")
        return commit[:7] if commit else "unknown"
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
        return bool(_build_info(repo).get("source_dirty"))
    return bool(out.stdout.strip())
