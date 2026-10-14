"""Read local UTF-8 reports through directory descriptors; never follow report symlinks."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import stat

MAX_BYTES = 512 * 1024
MAX_FILES = 200
MAX_ENTRIES = 2000
SUFFIXES = {".md", ".markdown", ".txt"}
FLAGS = os.O_RDONLY | os.O_NOFOLLOW
DIR_FLAGS = FLAGS | os.O_DIRECTORY

# Reject every symlink component, including ancestors of a report root.
def open_directory(path: Path):
    path = path.expanduser().absolute()
    if ".." in path.parts:
        raise OSError("Invalid report folder")
    fd = os.open(path.anchor, DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

SECRET_NAMES = {"secrets", "secret", "credentials", "credential", "config", "private",
                "keys", "key", "tokens", "token", "passwords", "password", "auth", "oauth",
                "vault", "agent-tokens", "ssh", "aws", "gnupg", "keychains", "library",
                "codex", "grok", "openclaw", "git", "env", "kube", "docker", "azure", "gcloud", "keyring", "keyrings"}

def sensitive_component(name):
    return name.lower().lstrip(".") in SECRET_NAMES


class ReportsReader:
    def __init__(self, root: Path, hermes_root: Path | None = None):
        self.root = root.expanduser().absolute()
        self.roots = {"ops": self.root}
        if hermes_root is not None:
            self.roots["hermes"] = hermes_root.expanduser().absolute()

    def catalog(self):
        reports = []
        visited = 0
        limited = False
        sources = []
        source_id = "ops"
        def walk(fd, parts):
            nonlocal visited, limited
            with os.scandir(fd) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_ENTRIES:
                        limited = True
                        return
                    if entry.name.startswith(".") or sensitive_component(entry.name) or sensitive_component(Path(entry.name).stem):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        path_parts = (*parts, entry.name)
                        if stat.S_ISDIR(info.st_mode) and len(parts) < 2:
                            child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                            try: walk(child, path_parts)
                            finally: os.close(child)
                        elif stat.S_ISREG(info.st_mode) and Path(entry.name).suffix.lower() in SUFFIXES:
                            name = "/".join(path_parts)
                            identity = name if source_id == "ops" else f"{source_id}:{name}"
                            title = name
                            if source_id == "ops" and parts and parts[0] == "historic-archive":
                                title = "Historic (archived) · " + "/".join(path_parts[1:])
                            if source_id == "hermes":
                                header_fd = os.open(entry.name, FLAGS | os.O_NONBLOCK, dir_fd=fd)
                                with os.fdopen(header_fd, "rb") as header:
                                    if not stat.S_ISREG(os.fstat(header.fileno()).st_mode): continue
                                    line = header.read(256).decode("utf-8", "replace").splitlines()[0:1]
                                    if line and line[0].startswith("# Cron Job:"):
                                        title = line[0].split(":", 1)[1].strip()[:160] + " · " + Path(entry.name).stem.replace("_", " ")
                            reports.append({"id": hashlib.sha256(identity.encode()).hexdigest(), "name": name,
                                            "title": title,
                                            "source_id": source_id, "source": "Hermes cron archive" if source_id == "hermes" else "Ops report folder",
                                            "size": info.st_size, "modified_at": info.st_mtime,
                                            "readable": info.st_size <= MAX_BYTES})
                    except OSError:
                        continue
        for source_id, root in self.roots.items():
            source = {"id": source_id, "root": str(root), "available": False, "error": None}
            try:
                root_fd = open_directory(root)
                try:
                    walk(root_fd, ())
                    source["available"] = True
                finally: os.close(root_fd)
            except FileNotFoundError: pass
            except OSError: source["error"] = "Report folder is not readable or is a symlink."
            sources.append(source)
        reports.sort(key=lambda r: (-r["modified_at"], r["name"]))
        return {"reports": reports[:MAX_FILES], "available": any(s["available"] for s in sources),
                "error": next((s["error"] for s in sources if s["error"]), None), "sources": sources,
                "limited": limited or len(reports) > MAX_FILES, "root": str(self.root)}

    def read(self, report_id):
        report = next((r for r in self.catalog()["reports"] if r["id"] == report_id), None)
        if report is None:
            raise FileNotFoundError()
        fd = open_directory(self.roots[report["source_id"]])
        try:
            parts = report["name"].split("/")
            for part in parts[:-1]:
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(parts[-1], FLAGS | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise FileNotFoundError()
                if info.st_size > MAX_BYTES:
                    raise ValueError("Report is larger than the 512 KiB preview limit.")
                content = source.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise ValueError("Report is larger than the 512 KiB preview limit.")
                try:
                    text = content.decode("utf-8-sig")
                except UnicodeError:
                    raise ValueError("Only UTF-8 text reports can be previewed.") from None
                if "\x00" in text:
                    raise ValueError("Only UTF-8 text reports can be previewed.")
                response_only = False
                if report["source_id"] == "hermes" and text.startswith("# Cron Job:") and "\n## Prompt\n" in text and "\n## Response\n" in text:
                    header = text.split("\n## Prompt\n", 1)[0]
                    body = text.split("\n## Response\n", 1)[1]
                    text = header + "\n\n## Response\n" + body
                    response_only = True
                return {**report, "size": len(content), "modified_at": info.st_mtime, "response_only": response_only,
                        "content": text, "format": "text" if parts[-1].lower().endswith(".txt") else "markdown"}
        finally:
            os.close(fd)
