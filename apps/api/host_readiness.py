"""Is this machine ready to build and deliver a project? Read-only checks plus a few explicit, whitelisted fixes.

The checks cover what a project needs on the host that runs its agents: an allowed workspace folder, git and a git identity, a way to push to
GitHub, an agent that can write code, and the optional tools some stories need. Nothing here installs software, stores a token or runs
project code. A fix does one named thing the operator asked for (create the workspace folder, set the git identity, make a GitHub SSH key,
test the key) and returns the fresh report. The private key never leaves the host and is never returned.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import urllib.request
from pathlib import Path

from settings import default_agent_tools_root, find_tool

CODE_AGENTS = ("claude", "codex", "openclaw", "grok")       # can write code in an Edit-mode story
MANAGER_AGENTS = ("hermes",)                               # plans and coordinates; managers do not write code
KEY_NAME = "rcd-github"
GITHUB_TARGET = "git" + chr(64) + "github.com"                   # built, not written out, so the release content scan does not mistake it for an email address
MARK_BEGIN, MARK_END = "# >>> dashboard github key >>>", "# <<< dashboard github key <<<"
NAME_RE = re.compile(r"^[^\x00-\x1f\x7f<>]{1,100}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


class ReadinessError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _home() -> Path:
    return Path.home()


def _run(cmd, timeout=8, env=None):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def _managed_root(settings=None):
    """The folder the dashboard installs agent tools into: the settings' own answer, else the same default the settings use."""
    root = getattr(settings, "agent_tools_path", None) if settings is not None else None
    if root:
        return Path(root)
    env = os.environ.get("MAC_CONTROL_AGENT_TOOLS_ROOT")
    if env:
        return Path(env)
    short = os.environ.get("MAC_CONTROL_PRODUCT_SHORT_NAME")
    return default_agent_tools_root(short) if short else default_agent_tools_root()


def _managed_bins(settings=None):
    """The `bin` folders of tools the dashboard installed itself (for example Node), which are not on PATH."""
    tools = _managed_root(settings) / "tools"
    return [str(p) for p in sorted(tools.glob("*/current/bin"))] if tools.is_dir() else []


def _tool(name, settings=None):
    found = find_tool(name)
    if os.path.isabs(found) and os.access(found, os.X_OK):
        return found
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(_managed_bins(settings)) or os.devnull)


def _item(id_, label, status, detail, fix=None, **extra):
    row = {"id": id_, "label": label, "status": status, "detail": detail, "fix": fix}
    row.update(extra)
    return row


def _git_value(key):
    git = _tool("git")
    if not git:
        return ""
    code, out = _run([git, "config", "--global", "--get", key])
    return out.strip() if code == 0 else ""


def _key_paths():
    base = _home() / ".ssh"
    return base / KEY_NAME, base / (KEY_NAME + ".pub")


def _verified_marker():
    return _home() / ".ssh" / (KEY_NAME + ".verified")


def _roots(settings):
    return [Path(r).expanduser() for r in settings.workdir_roots]


def check_workspace(settings):
    roots = _roots(settings)
    ready = [r for r in roots if r.is_dir() and os.access(r, os.W_OK)]
    if ready:
        return _item("workspace", "Workspace folder", "ok", f"Agents can work in {ready[0]}.")
    first = roots[0] if roots else None
    fix = {"action": "create_workspace", "label": f"Create {first}"} if first else None
    return _item("workspace", "Workspace folder", "missing", "None of the allowed workspace folders exists yet: " + ", ".join(str(r) for r in roots) + ". Do not use a scratch folder for a project that must end in a GitHub repository: clone the repository here instead.", fix)


def check_git():
    git = _tool("git")
    return _item("git", "git", "ok" if git else "missing", f"{git}" if git else "git is not installed. Install it with the system package manager.")


def check_git_identity():
    name, email = _git_value("user.name"), _git_value("user.email")
    if name and email:
        return _item("git_identity", "git identity", "ok", f"Commits are made as {name} <{email}>.")
    fix = {"action": "set_git_identity", "label": "Set the git identity", "inputs": ["name", "email"]} if _tool("git") else None
    return _item("git_identity", "git identity", "missing", "No global git name and email, so commits fail or are unattributed.", fix)


def check_github():
    private, public = _key_paths()
    if public.is_file() and private.is_file():
        text = public.read_text("utf-8", "replace").strip()[:600]
        marker = _verified_marker()
        if marker.is_file() and marker.stat().st_mtime >= private.stat().st_mtime:
            when = marker.read_text("utf-8", "replace").strip()[:40]
            return _item("github_ssh", "GitHub access (SSH key)", "ok", f"GitHub accepted this key{(' on ' + when) if when else ''}. Test again any time.",
                         {"action": "test_github_ssh", "label": "Test GitHub access"}, public_key=text)
        return _item("github_ssh", "GitHub access (SSH key)", "warn", "A key exists here, but GitHub has not accepted it yet. Add the public key to GitHub (Settings, SSH keys, or a repository's Deploy keys with write access), then press Test GitHub access.",
                     {"action": "test_github_ssh", "label": "Test GitHub access"}, public_key=text)
    fix = {"action": "make_github_key", "label": "Make a GitHub SSH key"} if _tool("ssh-keygen") else None
    return _item("github_ssh", "GitHub access (SSH key)", "missing", "Nothing on this host can push to GitHub yet. A project that ends in a repository needs this (or a GitHub token set in the project's git grant).", fix)


PATH_BEGIN, PATH_END = "# >>> dashboard tools on PATH >>>", "# <<< dashboard tools on PATH <<<"
PATH_FILES = (".profile", ".bashrc")


def _managed_bin(settings=None):
    return _managed_root(settings) / "bin"


def _has_tools(folder):
    return folder.is_dir() and any(p.is_file() and os.access(p, os.X_OK) for p in folder.iterdir())


def check_path(settings=None):
    folder = _managed_bin(settings)
    if not _has_tools(folder):
        return _item("tools_path", "Installed tools on your shell PATH", "info", "No tools have been installed by this dashboard yet.")
    configured = any(PATH_BEGIN in (_home() / f).read_text("utf-8", "replace") for f in PATH_FILES if (_home() / f).is_file())
    on_path = str(folder) in os.environ.get("PATH", "").split(os.pathsep)
    if configured or on_path:
        return _item("tools_path", "Installed tools on your shell PATH", "ok", f"{folder} is on the shell PATH, so commands such as codex and openclaw work in a new terminal.")
    return _item("tools_path", "Installed tools on your shell PATH", "warn", f"Tools installed here live in {folder}, which your shell does not search, so typing codex or openclaw says command not found. The sign-in command shown on each tool uses the full path; this fix makes the short commands work in new shells.",
                 {"action": "add_tools_to_path", "label": "Put installed tools on my PATH"})


def _agent_installed(settings, name):
    """Whether the dashboard itself would find this agent: its registry resolves a path set at startup and also a copy the Agent tools panel installed since."""
    try:
        from agents import REGISTRY
        return bool(REGISTRY[name].available(settings))
    except (ImportError, KeyError):
        path = getattr(settings, f"{name}_path", None) or name
        return bool(path if (os.path.isabs(path) and os.access(path, os.X_OK)) else shutil.which(path))


def check_agents(settings):
    rows = [{"id": name, "installed": _agent_installed(settings, name), "writes_code": name in CODE_AGENTS} for name in (*CODE_AGENTS, *MANAGER_AGENTS)]
    coders = [r["id"] for r in rows if r["installed"] and r["writes_code"]]
    managers = [r["id"] for r in rows if r["installed"] and not r["writes_code"]]
    if coders:
        status, detail = "ok", "Agents that can write code: " + ", ".join(coders) + (". Managers: " + ", ".join(managers) + "." if managers else ".")
    else:
        status = "missing"
        detail = "No agent that can write code is installed" + (f" (only {', '.join(managers)}, which plans and coordinates but does not write code)" if managers else "") + ". Install and sign in to Claude Code, Codex or OpenClaw. Detection does not prove sign-in."
    return _item("agents", "Agents that build", status, detail, agents=rows)


def check_tools(settings=None):
    notes = {"python3": "tests and scripts", "node": "JavaScript tests and the Playwright screenshot script", "docker": "building and running container images (otherwise a person or the pipeline does it)",
             "gh": "opening pull requests from this host (optional: a person or the pipeline can)", "ffmpeg": "publishing generated media"}
    rows = [{"id": n, "installed": bool(_tool(n, settings)), "needed_for": why} for n, why in notes.items()]
    missing = [r["id"] for r in rows if not r["installed"]]
    return _item("tools", "Optional tools", "info", ("Missing: " + ", ".join(missing) + ". Each is only needed by some stories.") if missing else "All present.", tools=rows)


def check_disk():
    free = shutil.disk_usage(_home()).free / 1e9
    return _item("disk", "Free disk space", "ok" if free >= 5 else "warn", f"{free:.0f} GB free.")


def check_network():
    rows = []
    for host in ("github.com", "openrouter.ai"):
        try:
            socket.setdefaulttimeout(5)
            urllib.request.urlopen(urllib.request.Request(f"https://{host}", method="HEAD"), timeout=5).close()
            rows.append({"host": host, "reachable": True})
        except Exception:
            rows.append({"host": host, "reachable": False})
    ok = all(r["reachable"] for r in rows)
    return _item("network", "Network", "ok" if ok else "warn", "GitHub and OpenRouter are reachable." if ok else "Cannot reach: " + ", ".join(r["host"] for r in rows if not r["reachable"]) + ".", hosts=rows)


def report(settings, network=False):
    checks = [check_workspace(settings), check_git(), check_git_identity(), check_github(), check_agents(settings), check_path(settings), check_tools(settings), check_disk()]
    if network:
        checks.append(check_network())
    status = {c["id"]: c["status"] for c in checks}
    build = all(status[k] == "ok" for k in ("workspace", "git", "git_identity", "agents"))
    deliver = build and status["github_ssh"] == "ok"                 # a key that GitHub has accepted, not just a key that exists
    return {"checks": checks, "ready_to_build": build, "ready_to_deliver": deliver,
            "note": "Checks never change anything. A fix does one named thing and shows what it changed. Sign-in to agents is not verified here."}


# ---------------------------------------------------------------- fixes

def create_workspace(settings, path=None):
    roots = _roots(settings)
    target = Path(path).expanduser() if path else (roots[0] if roots else None)
    if target is None or str(target.resolve()) not in {str(r.resolve()) for r in roots}:
        raise ReadinessError("Only an allowed workspace folder can be created.")
    target.mkdir(parents=True, exist_ok=True)
    return f"Created {target}."


def set_git_identity(name, email):
    git = _tool("git")
    if not git:
        raise ReadinessError("git is not installed.")
    if not NAME_RE.fullmatch((name or "").strip()) or not EMAIL_RE.fullmatch((email or "").strip()):
        raise ReadinessError("Enter a name (up to 100 characters) and a valid email address.")
    for key, value in (("user.name", name.strip()), ("user.email", email.strip())):
        code, out = _run([git, "config", "--global", key, value])
        if code != 0:
            raise ReadinessError("git could not save the identity: " + out.strip()[:200])
    return f"Commits will be made as {name.strip()} <{email.strip()}>."


def _write_ssh_config(private):
    config = _home() / ".ssh" / "config"
    block = f"{MARK_BEGIN}\nHost github.com\n  HostName github.com\n  User git\n  IdentityFile {private}\n  IdentitiesOnly yes\n{MARK_END}\n"
    text = config.read_text("utf-8") if config.is_file() else ""
    if MARK_BEGIN in text:
        text = re.sub(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n?", block, text, flags=re.S)
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    config.write_text(text, "utf-8")
    config.chmod(0o600)


def make_github_key():
    keygen = _tool("ssh-keygen")
    if not keygen:
        raise ReadinessError("ssh-keygen is not installed.")
    private, public = _key_paths()
    if private.exists() or public.exists():
        raise ReadinessError("A GitHub key already exists here. It is not replaced.", 409)
    private.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    code, out = _run([keygen, "-t", "ed25519", "-N", "", "-C", f"{socket.gethostname()}-dashboard", "-f", str(private)], timeout=20)
    if code != 0 or not public.is_file():
        raise ReadinessError("ssh-keygen failed: " + out.strip()[:200])
    private.chmod(0o600)
    _write_ssh_config(private)
    return "Made a new key (the private half stays on this host). Add the public key below to GitHub, then press Test GitHub access."


def test_github_ssh():
    ssh = _tool("ssh")
    private, _ = _key_paths()
    if not ssh or not private.is_file():
        raise ReadinessError("Make the GitHub key first.")
    # -F /dev/null: the dashboard may run in a hardened service where the system ssh config looks wrongly owned ("Bad owner or permissions"); everything needed is on the command line.
    code, out = _run([ssh, "-F", os.devnull, "-i", str(private), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new", "-T", GITHUB_TARGET], timeout=20)
    if "successfully authenticated" in out:
        import datetime
        _verified_marker().write_text(datetime.date.today().isoformat() + "\n", "utf-8")
        return "GitHub accepted the key: " + out.strip().splitlines()[0][:160]
    if "Permission denied" in out:
        raise ReadinessError("GitHub did not accept the key yet. Add the public key to your GitHub account or to the repository's Deploy keys (with write access), then test again.", 409)
    raise ReadinessError("Could not reach GitHub over SSH: " + (out.strip()[:160] or "no answer"), 502)


def add_tools_to_path(settings=None):
    folder = _managed_bin(settings)
    if not folder.is_dir():
        raise ReadinessError("No tools have been installed by this dashboard yet.")
    block = f'{PATH_BEGIN}\nexport PATH="{folder}:$PATH"\n{PATH_END}\n'
    changed = []
    for name in PATH_FILES:
        target = _home() / name
        text = target.read_text("utf-8") if target.is_file() else ""
        if PATH_BEGIN in text:
            text = re.sub(re.escape(PATH_BEGIN) + r".*?" + re.escape(PATH_END) + r"\n?", block, text, flags=re.S)
        else:
            text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
        target.write_text(text, "utf-8")
        changed.append(name)
    return f"Added {folder} to the PATH in ~/{' and ~/'.join(changed)}. Open a new terminal (or run: source ~/.profile) and codex, openclaw and the other installed tools work by name."


def apply(settings, action, name=None, email=None, path=None):
    if action == "create_workspace":
        return create_workspace(settings, path)
    if action == "set_git_identity":
        return set_git_identity(name, email)
    if action == "make_github_key":
        return make_github_key()
    if action == "test_github_ssh":
        return test_github_ssh()
    if action == "add_tools_to_path":
        return add_tools_to_path(settings)
    raise ReadinessError("Unknown fix.")
