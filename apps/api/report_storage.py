"""Host-owned report source configuration. Never writes report contents."""
import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from reports import ReportsReader, open_directory, sensitive_component

ERROR = "Report folder must be an absolute local path inside an approved report folder, without symlinks or private folders."
CONFIG = "report-storage.json"


class ReportStorage:
    def __init__(self, settings):
        self.settings = settings
        self.lock = RLock()
        self.overrides = {}
        self.config_error = None
        self.allowed = []
        for root in (settings.data_dir / "reports", settings.ops_reports_dir,
                     settings.hermes_reports_dir, *settings.reports_allowed_roots):
            if root is not None:
                path = root.expanduser().absolute()
                if self.safe_shape(path) and path not in self.allowed:
                    self.allowed.append(path)
        try:
            fd = open_directory(settings.data_dir)
            try:
                config_fd = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(config_fd, "rb") as file:
                    import stat
                    if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                        raise ValueError()
                    content = file.read(16385)
                    if len(content) > 16384:
                        raise ValueError()
                    value = json.loads(content)
                    if not isinstance(value, dict) or set(value) - {"ops", "hermes"}:
                        raise ValueError()
                    for key, path in value.items():
                        if key == "ops" and path is None:
                            raise ValueError()
                        if path is not None:
                            if not isinstance(path, str):
                                raise ValueError()
                            self.validate(path, require_available=False)
                    self.overrides = value
            finally:
                os.close(fd)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            # Fail closed: a broken host override must never fall back to another source.
            self.config_error = "Saved report storage is unavailable. An operator must review the host configuration."

    def safe_shape(self, path):
        data = self.settings.data_dir.expanduser().absolute()
        broad = {Path(path.anchor), Path.home(), data, Path("/etc"), Path("/var"),
                 Path("/usr"), Path("/home"), Path("/Users"), Path("/private"), Path("/srv")}
        if not path.is_absolute() or ".." in path.parts or path in broad:
            return False
        for index, part in enumerate(path.parts[1:], 1):
            # /private is a macOS filesystem ancestor, not a report secret folder.
            if part == "private" and index == 1:
                continue
            if sensitive_component(part):
                return False
            prefix = Path(*path.parts[:index + 1])
            if part == ".hermes":
                if path.parts[index + 1:index + 3] != ("cron", "output"):
                    return False
            elif part.startswith(".") and not data.is_relative_to(prefix):
                return False
        return True

    def validate(self, value, require_available=True):
        if not value or not Path(value).is_absolute() or "\x00" in value or len(value) > 4096:
            raise ValueError(ERROR)
        path = Path(value)
        if not self.safe_shape(path) or not any(path.is_relative_to(root) for root in self.allowed):
            raise ValueError(ERROR)
        try:
            fd = open_directory(path)
            os.close(fd)
        except FileNotFoundError:
            if require_available:
                raise ValueError("Report folder is unavailable. Create the approved folder on the host first.") from None
        except OSError:
            raise ValueError(ERROR) from None
        return path

    def reader(self):
        roots = {"ops": self.settings.reports_path, "hermes": self.settings.hermes_reports_dir}
        roots.update(self.overrides)
        if self.config_error:
            return None
        reader = ReportsReader(Path(roots["ops"] or self.settings.data_dir / "reports"), Path(roots["hermes"]) if roots["hermes"] else None)
        for key in list(reader.roots):
            try:
                self.validate(str(reader.roots[key]), require_available=False)
            except ValueError:
                del reader.roots[key]
        return reader

    def catalog(self):
        with self.lock:
            reader = self.reader()
            result = reader.catalog() if reader else {"reports": [], "sources": [], "available": False, "limited": False, "root": "", "error": self.config_error}
            by_id = {s["id"]: s for s in result["sources"]}
            sources = []
            for key, initial in (("ops", self.settings.reports_path), ("hermes", self.settings.hermes_reports_dir)):
                value = self.overrides.get(key, initial)
                mode = "configured" if key in self.overrides or (self.settings.ops_reports_dir if key == "ops" else initial) else "default"
                if value is None:
                    mode = "disabled"
                source = by_id.get(key, {"id": key, "root": str(value) if value else "", "available": False, "error": self.config_error or ("Report folder is unavailable or not approved." if value else None)})
                sources.append({**source, "mode": mode, "state": mode if source["available"] else "unavailable"})
            return {**result, "sources": sources}

    def status(self):
        return {"sources": self.catalog()["sources"], "allowed_roots": [str(p) for p in self.allowed],
                "error": self.config_error, "scope": "host", "read_only": True}

    def configure(self, ops, hermes, reset=False):
        with self.lock:
            value = {} if reset else {"ops": str(self.validate(ops)), "hermes": str(self.validate(hermes)) if hermes else None}
            fd = open_directory(self.settings.data_dir)
            temporary = f".report-storage-{uuid4().hex}.tmp"
            try:
                out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                with os.fdopen(out, "w") as file:
                    json.dump(value, file)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, CONFIG, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass
                os.close(fd)
            self.overrides = value
            self.config_error = None
            return self.status()

    def read(self, report_id):
        with self.lock:
            reader = self.reader()
            if reader is None:
                raise FileNotFoundError()
            return reader.read(report_id)
