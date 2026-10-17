"""mac-control API settings.

Loaded from environment variables prefixed MAC_CONTROL_, then from
~/.rcd-control/.env. Defaults are safe for this Mac: the server binds to
127.0.0.1 until Google sign-in exists (Phase 4). Set MAC_CONTROL_HOST=0.0.0.0
only after auth is enforced on every route.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Literal
import sys

from pydantic import Field, SecretStr, model_validator
from urllib.parse import urlsplit
import ipaddress
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / ".rcd-control"
REPO_ROOT = Path(__file__).resolve().parents[2]
IS_MACOS = sys.platform == "darwin"


def default_agent_tools_root(product_short_name: str = "RCD") -> Path:
    """Where the Agent tools panel installs the agent CLIs (per user, no sudo): one folder, removable as a whole."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / ("rcd-agent-tools" if product_short_name.upper() == "RCD" else "mcd-agent-tools")


def tool_search_dirs() -> tuple[str, ...]:
    """Folders searched for optional tools: managed installs, PATH, then common user folders."""
    managed = os.environ.get("MAC_CONTROL_AGENT_TOOLS_ROOT") or str(default_agent_tools_root(os.environ.get("MAC_CONTROL_PRODUCT_SHORT_NAME", "RCD")))
    extra = [str(Path.home() / ".local" / "bin"), str(Path.home() / ".grok" / "bin"), "/usr/local/bin"]
    if IS_MACOS:
        extra.append("/opt/homebrew/bin")  # Homebrew's standard Apple-silicon prefix
    return tuple(dict.fromkeys(d for d in (os.path.join(managed, "bin"), *os.environ.get("PATH", "").split(os.pathsep), *extra) if d))


def find_tool(name: str) -> str:
    """First executable `name` on the search path, else the bare name.

    A bare name keeps the integration optional: it shows as unavailable and setup never fails.
    Set the matching MAC_CONTROL_*_PATH variable to pin an explicit location.
    """
    for d in tool_search_dirs():
        candidate = Path(d) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAC_CONTROL_",
        env_file=str(DEFAULT_DATA_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: str = Field(default="local", description="local | test")
    organization_name: str = Field(default="RCD")
    product_name: str = Field(default="Raspberry Pi Control Dashboard")
    product_short_name: str = Field(default="RCD")
    host: str = Field(
        default="127.0.0.1",
        description="Bind address. Stays 127.0.0.1 until Phase 4 auth is enforced.",
    )
    port: int = Field(default=8800, ge=1, le=65535)
    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    web_dist: Path = Field(
        default=REPO_ROOT / "apps" / "web" / "dist",
        description="Built Vue app. Served at / when present.",
    )
    log_level: str = Field(default="info")

    # --- Phase 2: collector ---------------------------------------------
    collector_enabled: bool = Field(default=True, description="Off in tests.")
    sample_interval_s: int = Field(default=10, ge=2, le=300)
    # macmon remains the macOS source; Linux uses psutil, /proc and sysfs.
    macmon_path: str = Field(default_factory=lambda: find_tool("macmon"))
    tailscale_path: str = Field(default_factory=lambda: find_tool("tailscale"))
    disk_path: str = Field(default="/System/Volumes/Data" if IS_MACOS else "/")
    service_prefixes: tuple[str, ...] = Field(
        default=("ai.hermes.", "ai.openclaw.", "com.openclaw.", "com.headroom.", "com.operator.")
        + (() if IS_MACOS else ("rcd-",)),
        description="Service names (launchd labels on macOS, systemd user units on Linux) with "
        "these prefixes appear on the Services panel.",
    )

    # --- Phase 3: task board and agent dispatch ----------------------------
    dispatcher_enabled: bool = Field(default=True, description="Off in tests.")
    max_concurrent_runs: int = Field(default=2, ge=1, le=8)
    project_auto_accept_low: bool = Field(default=False, description="Parallel builds only: accept a low-risk story handoff on its own when its run succeeded without an incomplete report and every file it changed is inside the files it declared. Off by default.")
    default_timeout_s: int = Field(default=1800, ge=30, le=6 * 3600)
    run_quiet_after_s: int = Field(default=600, ge=30, le=6 * 3600,
                                   description="A live runner silent this long is shown as quiet, not as working.")
    default_budget_usd: float = Field(default=0.0, ge=0.0, le=50.0)
    dispatch_free_only: bool = Field(default=True)
    housekeeping_auto: str = Field(default="", description="Comma-separated housekeeping finding kinds cleaned up automatically after hours (stale_approval_wait, old_update_backup). Empty: nothing is automatic.")
    housekeeping_window_start_hour: int = Field(default=1, ge=0, le=23)
    housekeeping_window_end_hour: int = Field(default=5, ge=0, le=23)
    model_watch_enabled: bool = Field(default=False, description="Run the weekly model watch: read OpenRouter's public model list and leave a Backlog card when something needs a person. Off by default.")
    model_watch_interval_days: int = Field(default=7, ge=1, le=30)
    model_refresh_enabled: bool = Field(default=True, description="Allow the operator to read OpenRouter's public model list from the Models section. Off: nothing is fetched.")
    dispatch_max_budget_usd: float = Field(default=0.0, ge=0.0, le=50.0)
    agent_git_grants_file: Path = Field(
        default=DEFAULT_DATA_DIR / "agent-git" / "grants.json",
        description="Operator-owned branch-scoped git grants for project stories (see agent_git.py).",
    )
    agent_permissions: Literal["working", "strict"] = Field(
        default="working",
        description="What agents may run in a project's working folder. working (the default) lets an Edit story run test and syntax runners, harmless helpers and package installs, and gives Codex the package "
                    "indexes and GitHub, so a project can finish out of the box. strict allows only agent_extra_commands and gives Codex its plain sandbox. Git grants and branch rules apply either way.",
    )
    agent_extra_commands: tuple[str, ...] = Field(
        default=(), description="Extra Claude command rules, each written Bash(command:*), allowed in every Edit story in either mode.")
    agent_extra_network_domains: tuple[str, ...] = Field(
        default=(), description="Extra hostnames a Codex Edit story may reach, beyond GitHub and the package indexes (working mode and git grants).")
    dispatch_route_classes: dict[str, str] = Field(
        default_factory=dict,
        description="Reviewed exact agent|target|model routes: free, subscription or paid. Unknown denies.",
    )
    approval_ttl_s: int = Field(default=24 * 3600, ge=60, le=7 * 86400,
                                description="An unused task approval expires after this many seconds.")
    workdir_roots: tuple[Path, ...] = Field(
        default=(Path.home() / "Projects", DEFAULT_DATA_DIR / "workspaces"),
        description="A card's working directory must be inside one of these.",
    )
    claude_path: str = Field(default_factory=lambda: find_tool("claude"))
    codex_path: str = Field(default_factory=lambda: find_tool("codex"))
    grok_path: str = Field(default_factory=lambda: find_tool("grok"))
    hermes_path: str = Field(default_factory=lambda: find_tool("hermes"))
    openclaw_path: str = Field(default_factory=lambda: find_tool("openclaw"))
    hermes_config_path: Path | None = None
    openclaw_config_path: Path | None = None
    agent_executables: tuple[str, ...] = Field(
        default=("claude", "codex", "grok", "agent", "hermes", "openclaw"),
        description="Processes started from these executables (and their children) are agents: "
                    "operator APIs refuse them, as they refuse every dispatched runner.",
    )
    run_retention_days: int = Field(default=90, ge=1)
    allowed_hosts_extra: tuple[str, ...] = Field(
        default=(), description="Extra Host values the request guard accepts (tests only)."
    )
    dev_port: int = Field(default=5173, description="Vite dev server port, allowed by the guard.")

    # --- Phase 7: one local alert rules file ------------------------------
    alerts_config_path: Path | None = None

    @property
    def alerts_path(self) -> Path:
        return self.alerts_config_path or self.data_dir / "alerts.toml"

    # --- Phase 6: read-only operations panels ----------------------------
    github_writes_enabled: bool = False
    bug_intake_enabled: bool = False
    bug_intake_poll_seconds: int = Field(default=900, ge=120, le=86400)
    gh_path: str = Field(default_factory=lambda: find_tool("gh"))
    ops_reports_dir: Path | None = None
    hermes_reports_dir: Path | None = None
    reports_allowed_roots: tuple[Path, ...] = Field(default=(), description="Host-approved local report folders.")
    ops_collectors_enabled: bool = Field(default=False, description="Scheduled Ops collectors; off until the operator enables them.")
    ops_collector_commands: tuple[str, ...] = Field(default=(), description="Absolute executables a collector command source may run.")

    # --- Packaged updates: off unless a helper-managed update root is set up -------
    update_root: Path | None = Field(default=None, description="Install root with helper/helper.json; see packaging/README.md.")

    # --- Agent tools panel: where the pinned agent CLIs are installed (per user, no sudo) ---------
    agent_tools_root: Path | None = Field(default=None, description="Install folder for the Agent tools panel; see docs/install/agent-tools.md.")

    @property
    def agent_tools_path(self) -> Path:
        return self.agent_tools_root or default_agent_tools_root(self.product_short_name)

    @property
    def reports_path(self) -> Path:
        return self.ops_reports_dir or self.data_dir / "reports"

    # --- Phase 4: opt-in Google sign-in. Enabling requires complete local configuration.
    auth_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    auth_allowed_emails: tuple[str, ...] = ()
    auth_origins: tuple[str, ...] = ("http://127.0.0.1:8800",)

    @model_validator(mode="after")
    def validate_auth(self):
        for origin in self.auth_origins:
            u = urlsplit(origin)
            try:
                local = u.hostname == "localhost" or ipaddress.ip_address(u.hostname or "").is_loopback
            except ValueError:
                local = False
            if (not u.hostname or u.username or u.password or u.path or u.query or u.fragment
                    or origin != f"{u.scheme}://{u.netloc}"
                    or u.scheme not in ("http", "https")
                    or (u.scheme == "http" and not local)):
                raise ValueError("Auth origins require a canonical HTTPS origin or HTTP loopback origin")
        if self.auth_enabled and (not self.google_client_id or not self.google_client_secret.get_secret_value()
                                  or not self.auth_allowed_emails or not self.auth_origins):
            raise ValueError("Google sign-in needs client credentials, an email allowlist and auth origins")
        return self

    @property
    def db_path(self) -> Path:
        return self.data_dir / "data.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
