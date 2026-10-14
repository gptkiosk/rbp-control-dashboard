"""Host-owned, secret-free configuration for the optional GitHub reader."""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
LOGIN = re.compile(r"[A-Za-z0-9-]{1,39}\Z")
CONFIG = "github.json"

@dataclass(frozen=True)
class GithubConfig:
    enabled: bool = False
    account: str = ""
    repos: tuple[str, ...] = ()
    public_only: bool = False
    poll_seconds: int = 900
    version: int = 1
    @property
    def configured(self) -> bool: return self.enabled and bool(self.account) and bool(self.repos)
    def public(self) -> dict: return {**asdict(self), "repos": list(self.repos), "configured": self.configured, "secrets_stored": False}

class GithubConfigStore:
    """A 0600 JSON file. Absence is an explicit migration-needed, no-call state."""
    def __init__(self, data_dir: Path):
        self.data_dir=Path(data_dir);self.lock=RLock();self.error=None;self._config=None;self._load()
    def _decode(self,value):
        if not isinstance(value,dict) or set(value)!={"version","enabled","account","repos","public_only","poll_seconds"}:raise ValueError()
        if value["version"]!=1 or type(value["enabled"]) is not bool or type(value["public_only"]) is not bool:raise ValueError()
        if not isinstance(value["account"],str) or (value["enabled"] and not LOGIN.fullmatch(value["account"])) or (not value["enabled"] and value["account"] and not LOGIN.fullmatch(value["account"])):raise ValueError()
        if not isinstance(value["repos"],list) or (value["enabled"] and not value["repos"]) or len(value["repos"])>100:raise ValueError()
        if any(not isinstance(repo,str) or not SLUG.fullmatch(repo) for repo in value["repos"]):raise ValueError()
        if len(set(value["repos"]))!=len(value["repos"]) or type(value["poll_seconds"]) is not int or not 300<=value["poll_seconds"]<=86400:raise ValueError()
        return GithubConfig(value["enabled"],value["account"],tuple(value["repos"]),value["public_only"],value["poll_seconds"],1)
    def _load(self):
        try:
            fd=os.open(self.data_dir,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                config_fd=os.open(CONFIG,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                with os.fdopen(config_fd,"rb") as source:
                    info=os.fstat(source.fileno());raw=source.read(16385)
                    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>16384:raise ValueError()
                self._config=self._decode(json.loads(raw))
            finally:os.close(fd)
        except FileNotFoundError:self._config=None
        except (OSError,ValueError,TypeError,json.JSONDecodeError):self.error="Saved GitHub configuration is unavailable. An operator must review it."
    def status(self):
        with self.lock:
            if self.error:return {"state":"configuration_error","configured":False,"error":self.error}
            if self._config is None:return {"state":"migration_required","configured":False,"message":"GitHub is optional. Migrate existing preferences or configure an allowlist to enable it."}
            state="ready" if self._config.configured else "disabled" if not self._config.enabled else "unconfigured"
            return {"state":state,**self._config.public()}
    def config(self):
        with self.lock:return self._config if self._config and self._config.configured and not self.error else None
    def save(self,value):
        config=self._decode(value);self.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        with self.lock:
            fd=os.open(self.data_dir,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);temporary=f".github-{uuid4().hex}.tmp"
            try:
                out=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                with os.fdopen(out,"w") as target:target.write(json.dumps(asdict(config),sort_keys=True,separators=(",",":")));target.flush();os.fsync(target.fileno())
                os.replace(temporary,CONFIG,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
            finally:
                try:os.unlink(temporary,dir_fd=fd)
                except FileNotFoundError:pass
                os.close(fd)
            self._config=config;self.error=None;return self.status()
