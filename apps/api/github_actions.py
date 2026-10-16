"""Operator-only GitHub action gate. No automatic writes, retries, or scope changes."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from dataclasses import asdict

from github_config import SLUG

TTL = 900
SHA = re.compile(r"[a-f0-9]{40}\Z")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}\Z")


class ActionError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def plan(value):
    """Strict schema; remote text and arbitrary endpoints/CLI flags are never instructions."""
    if not isinstance(value, dict) or set(value) != {"kind", "repo", "content"}:
        raise ActionError("An exact kind, repository and content are required.", 422)
    kind, repo, content = value["kind"], value["repo"], value["content"]
    if not isinstance(repo, str) or not SLUG.fullmatch(repo) or any(x in {".", ".."} for x in repo.split("/")):
        raise ActionError("Invalid repository.", 422)
    repo = repo.lower()
    schemas = {
        "issue": {"title", "body"}, "comment": {"number", "body"},
        "pr": {"title", "body", "head", "base", "head_sha", "base_sha", "draft"},
        "merge": {"number", "head_sha", "method", "commit_title", "commit_message"},
        "publication": {"tag", "target_sha", "name", "body", "prerelease"},
        "repository": {"name", "description"},
    }
    optional = {"issue": {"labels"}}.get(kind, set()) if isinstance(kind, str) else set()
    if (not isinstance(kind, str) or kind not in schemas or not isinstance(content, dict)
            or not schemas[kind] <= set(content) <= schemas[kind] | optional):
        raise ActionError("Unsupported action or content fields.", 422)
    for key, item in content.items():
        if key == "labels":
            valid = (isinstance(item, list) and 1 <= len(item) <= 5
                     and all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,49}", x) for x in item))
        elif key in {"number"}:
            valid = type(item) is int and 1 <= item <= 2147483647
        elif key in {"draft", "prerelease"}:
            valid = type(item) is bool
        elif key.endswith("sha"):
            valid = isinstance(item, str) and bool(SHA.fullmatch(item))
        elif key in {"head", "base", "tag"}:
            valid = (isinstance(item, str) and bool(REF.fullmatch(item)) and ".." not in item
                     and "//" not in item and not item.endswith(("/", ".", ".lock")))
        elif key == "method":
            valid = isinstance(item, str) and item in {"merge", "squash", "rebase"}
        else:
            limit = 60000 if key in {"body", "commit_message"} else 256
            valid = isinstance(item, str) and len(item.encode()) <= limit and "\x00" not in item
            if key in {"title", "name", "commit_title"}:
                valid = valid and bool(item.strip()) and "\n" not in item and "\r" not in item
            elif key == "description":
                valid = valid and "\n" not in item and "\r" not in item
        if not valid:
            raise ActionError("Invalid action content.", 422)
    if kind == "repository":
        # The repository is created under the signed-in account, always private. The name must be the repository part of `repo`.
        if repo.split("/")[1] != content["name"].lower() or not REPO_NAME.fullmatch(content["name"]) or content["name"].lower().endswith(".git"):
            raise ActionError("Invalid repository name.", 422)
    root = f"repos/{repo}"
    if kind == "issue":
        method, endpoint, payload = "POST", root + "/issues", dict(content)
        destination = f"https://github.com/{repo}/issues"
    elif kind == "repository":
        # private and the initial commit are fixed here; the request cannot ask for anything else.
        method, endpoint = "POST", "user/repos"
        payload = {"name": content["name"], "description": content["description"], "private": True, "auto_init": True}
        destination = f"https://github.com/{repo}"
    elif kind == "comment":
        method, endpoint, payload = "POST", root + f"/issues/{content['number']}/comments", {"body": content["body"]}
        destination = f"https://github.com/{repo}/issues/{content['number']}"
    elif kind == "pr":
        if content["head"] == content["base"]:
            raise ActionError("PR head and base must differ.", 422)
        method, endpoint = "POST", root + "/pulls"
        payload = {k: content[k] for k in ("title", "body", "head", "base", "draft")}
        destination = f"https://github.com/{repo}/compare/{quote(content['base'], safe='')}...{quote(content['head'], safe='')}"
    elif kind == "merge":
        method, endpoint = "PUT", root + f"/pulls/{content['number']}/merge"
        payload = {"sha": content["head_sha"], "merge_method": content["method"],
                   "commit_title": content["commit_title"], "commit_message": content["commit_message"]}
        destination = f"https://github.com/{repo}/pull/{content['number']}"
    else:
        method, endpoint = "POST", root + "/releases"
        payload = {"tag_name": content["tag"], "target_commitish": content["target_sha"],
                   "name": content["name"], "body": content["body"], "draft": False,
                   "prerelease": content["prerelease"], "generate_release_notes": False, "make_latest": "false"}
        destination = f"https://github.com/{repo}/releases/tag/{quote(content['tag'], safe='')}"
    return {"kind": kind, "repo": repo, "content": content, "destination": destination,
            "method": method, "endpoint": endpoint, "payload": payload}


class GithubActionTransport:
    """Fixed github.com REST requests with JSON stdin; never shell, git push or token export."""
    def __init__(self, reader):
        self.reader = reader

    def request(self, method, endpoint, payload=None):
        argv = [self.reader.binary, "api", "--hostname", "github.com", "--method", method,
                endpoint, "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if payload is not None:
            argv += ["--input", "-"]
        result = subprocess.run(argv, input=canonical(payload) if payload is not None else None,
                                text=True, capture_output=True, timeout=15, check=False)
        # Never retain gh stdout/stderr (may contain identities, credentials or private data).
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise ActionError("GitHub did not acknowledge the request; inspect the destination before retrying.")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ActionError("GitHub acknowledgement was invalid; inspect the destination.")
        return value

    def preflight(self, preview):
        auth = self.reader.auth_status()
        if not auth["available"] or auth["account"].lower() != preview["account"].lower():
            raise ActionError("The reviewed GitHub account is no longer active.")
        if preview["kind"] == "repository":
            try:
                self.request("GET", f"repos/{preview['repo']}")
            except ActionError:
                return      # not found: the name is free
            raise ActionError("A repository with this name already exists.")
        repo = self.request("GET", f"repos/{preview['repo']}")
        if repo.get("full_name", "").lower() != preview["repo"].lower() or repo.get("archived") or repo.get("disabled"):
            raise ActionError("Repository identity or availability changed.")
        if preview["public_only"] and repo.get("private") is not False:
            raise ActionError("Public-only policy denies this repository.")
        c, root = preview["content"], f"repos/{preview['repo']}"
        if preview["kind"] == "pr":
            for ref in ("head", "base"):
                commit = self.request("GET", root + "/commits/" + quote(c[ref], safe=""))
                if commit.get("sha") != c[ref + "_sha"]:
                    raise ActionError("PR branch changed; draft and approve a new preview.")
        elif preview["kind"] == "merge":
            pr = self.request("GET", root + f"/pulls/{c['number']}")
            if pr.get("state") != "open" or pr.get("draft") is not False or pr.get("head", {}).get("sha") != c["head_sha"]:
                raise ActionError("PR state or approved head changed.")
        elif preview["kind"] == "publication":
            # Only an existing lightweight tag pinned to the exact approved commit is supported.
            ref = self.request("GET", root + "/git/ref/tags/" + quote(c["tag"], safe=""))
            if ref.get("object", {}).get("type") != "commit" or ref.get("object", {}).get("sha") != c["target_sha"]:
                raise ActionError("Publication requires an existing lightweight tag at the approved commit.")

    def send(self, preview):
        value = self.request(preview["method"], preview["endpoint"], preview["payload"])
        if preview["kind"] == "repository":
            if (type(value.get("id")) is not int or str(value.get("full_name", "")).lower() != preview["repo"].lower()
                    or value.get("private") is not True):
                raise ActionError("GitHub did not confirm a private repository; check it on GitHub now.")
            return {"acknowledged": True, "html_url": f"https://github.com/{preview['repo']}"}
        if preview["kind"] == "merge":
            if value.get("merged") is not True:
                raise ActionError("GitHub did not confirm the merge; inspect the PR.")
        elif type(value.get("id")) is not int:
            raise ActionError("GitHub acknowledgement was invalid; inspect the destination.")
        url = value.get("html_url")
        # Only a link back to the exact repository is passed on, and only for an issue.
        if preview["kind"] == "issue" and isinstance(url, str) and url.startswith(f"https://github.com/{preview['repo']}/issues/"):
            return {"acknowledged": True, "html_url": url}
        return {"acknowledged": True}


class GithubActionGuard:
    def __init__(self, data_dir, reader, *, enabled=False, clock=time.time, transport=None):
        self.path = Path(data_dir) / "github-actions.sqlite3"
        self.reader, self.enabled, self.clock = reader, enabled, clock
        self.transport = transport or GithubActionTransport(reader)
        # Private state is separate from the existing task database; no migration side effects.
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        info = self.path.lstat()
        import stat
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("GitHub action store must be an owner-only regular file.")
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS actions (
                  id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, preview TEXT NOT NULL,
                  state TEXT NOT NULL, nonce_hash TEXT, approved_by TEXT, expires REAL,
                  created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT, event TEXT NOT NULL,
                  actor TEXT NOT NULL, at REAL NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, db, action_id, event, actor):
        db.execute("INSERT INTO audit(action_id,event,actor,at) VALUES(?,?,?,?)", (action_id, event, actor, self.clock()))

    def policy(self, preview):
        config = self.reader.config()
        if config is not None and preview.get("kind") == "repository":
            # A new repository cannot be on the allowlist yet. It must be under the configured account, and a public-only host never creates private ones.
            if preview["repo"].split("/")[0].lower() != config.account.lower() or config.public_only:
                raise ActionError("A new repository can only be created under the configured GitHub account on a host that allows private repositories.")
            return config
        if config is None or preview["repo"] not in {r.lower() for r in config.repos}:
            raise ActionError("GitHub is disabled or repository is outside the host allowlist.")
        if preview.get("account", config.account) != config.account or preview.get("public_only", config.public_only) != config.public_only:
            raise ActionError("Host GitHub policy changed; draft a new preview.")
        return config

    def draft(self, value, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                preview = plan(value)
                config = self.policy(preview)
                preview.update(account=config.account, public_only=config.public_only)
            except ActionError:
                self.event(db, None, "draft_denied", actor)
                db.commit()
                raise
            fingerprint = digest(preview)
            old = db.execute("SELECT id FROM actions WHERE fingerprint=?", (fingerprint,)).fetchone()
            if old:
                self.event(db, old["id"], "duplicate_suppressed", actor)
                action_id = old["id"]
            else:
                action_id, now = secrets.token_hex(16), self.clock()
                db.execute("INSERT INTO actions VALUES(?,?,?,'draft',NULL,NULL,NULL,?,?)", (action_id, fingerprint, canonical(preview), now, now))
                self.event(db, action_id, "drafted", actor)
        return self.get(action_id)

    def row(self, db, action_id):
        row = db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("Action not found.", 404)
        if digest(json.loads(row["preview"])) != row["fingerprint"]:
            raise ActionError("Action preview integrity check failed.")
        return row

    def get(self, action_id):
        with self.connect() as db:
            row = self.row(db, action_id)
            return {"id": row["id"], "fingerprint": row["fingerprint"], "preview": json.loads(row["preview"]),
                    "state": row["state"], "approved_by": row["approved_by"], "expires_at": row["expires"],
                    "created_at": row["created"], "updated_at": row["updated"], "writes_enabled": self.enabled,
                    "audit": [dict(x) for x in db.execute("SELECT seq,event,actor,at FROM audit WHERE action_id=? ORDER BY seq", (action_id,))]}

    def review(self, action_id, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, action_id)
            if row["state"] not in {"draft", "approved"}:
                self.event(db, action_id, "review_denied", actor)
                db.commit()
                raise ActionError("This action has already been claimed or revoked.")
            nonce = secrets.token_urlsafe(32)
            db.execute("UPDATE actions SET state='draft', nonce_hash=?, approved_by=NULL, expires=?, updated=? WHERE id=?",
                       (digest(nonce), self.clock() + TTL, self.clock(), action_id))
            self.event(db, action_id, "previewed", actor)
        return {**self.get(action_id), "nonce": nonce, "question": "Authorize this exact GitHub destination and content for one execution?"}

    def approve(self, action_id, fingerprint, nonce, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, action_id)
            try:
                self.policy(json.loads(row["preview"]))
                if (row["state"] != "draft" or row["expires"] is None or row["expires"] <= self.clock()
                        or not isinstance(nonce, str) or not row["nonce_hash"]
                        or not hmac.compare_digest(row["nonce_hash"], digest(nonce)) or row["fingerprint"] != fingerprint):
                    raise ActionError("Approval is missing, expired, changed or already used.")
            except ActionError:
                self.event(db, action_id, "approval_denied", actor)
                db.commit()
                raise
            db.execute("UPDATE actions SET state='approved', approved_by=?, nonce_hash=NULL, updated=? WHERE id=?", (actor, self.clock(), action_id))
            self.event(db, action_id, "approved", actor)
        return self.get(action_id)

    def revoke(self, action_id, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, action_id)
            if row["state"] not in {"draft", "approved"}:
                self.event(db, action_id, "revocation_denied", actor)
                db.commit()
                raise ActionError("Claimed actions cannot be cancelled or retried.")
            db.execute("UPDATE actions SET state='revoked', nonce_hash=NULL, updated=? WHERE id=?", (self.clock(), action_id))
            self.event(db, action_id, "revoked", actor)
        return self.get(action_id)

    def execute(self, action_id, fingerprint, actor):
        # Commit a permanent claim BEFORE any remote operation. Concurrent/restarted calls
        # cannot resend even when the remote acknowledgement or local process is lost.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.row(db, action_id)
            preview = json.loads(row["preview"])
            try:
                if not self.enabled:
                    raise ActionError("External GitHub writes are disabled on this host.")
                self.policy(preview)
                if row["state"] != "approved" or row["approved_by"] != actor or row["expires"] <= self.clock() or row["fingerprint"] != fingerprint:
                    raise ActionError("A current exact approval by this operator is required.")
            except ActionError:
                self.event(db, action_id, "execution_denied", actor)
                db.commit()
                raise
            db.execute("UPDATE actions SET state='claimed', updated=? WHERE id=?", (self.clock(), action_id))
            self.event(db, action_id, "claimed", actor)
        try:
            self.transport.preflight(preview)
        except Exception:
            self.finish(action_id, "blocked", actor)
            raise ActionError("GitHub preflight refused or failed. No write was attempted; inspect the audit and destination.") from None
        try:
            result = self.transport.send(preview)
        except Exception:
            self.finish(action_id, "uncertain", actor)
            raise ActionError("Delivery is uncertain. Inspect the exact GitHub destination; this action will not be resent.") from None
        self.finish(action_id, "succeeded", actor)
        if preview["kind"] == "repository":
            self._allow(action_id, preview, actor)
        return {**self.get(action_id), "result": result if isinstance(result, dict) else {}}

    def _allow(self, action_id, preview, actor):
        """Put the repository this approval created on the host allowlist, as the approved preview said it would. A failure here never undoes the creation."""
        try:
            store = getattr(self.reader, "config_store", None)
            config = store.config() if store else None
            if config is None or len(config.repos) >= 100:
                raise ValueError()
            value = {**asdict(config), "repos": [*config.repos, preview["repo"]]}
            store.save(value)
            event = "allowlisted"
        except Exception:   # noqa: BLE001
            event = "allowlist_failed"
        with self.connect() as db:
            self.event(db, action_id, event, actor)

    def pending(self):
        """Drafts waiting for a decision, newest first, with their exact previews."""
        with self.connect() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM actions WHERE state='draft' ORDER BY created DESC LIMIT 50")]
        out = []
        for action_id in ids:
            try:
                out.append(self.get(action_id))
            except ActionError:
                continue    # a tampered row is never shown as something to approve
        return out

    def recent(self, kind, limit=10):
        with self.connect() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM actions ORDER BY created DESC LIMIT 200")]
        out = []
        for action_id in ids:
            try:
                item = self.get(action_id)
            except ActionError:
                continue
            if item["preview"].get("kind") == kind:
                out.append(item)
            if len(out) >= limit:
                break
        return out

    def finish(self, action_id, state, actor):
        with self.connect() as db:
            db.execute("UPDATE actions SET state=?, updated=? WHERE id=? AND state='claimed'", (state, self.clock(), action_id))
            self.event(db, action_id, state, actor)
