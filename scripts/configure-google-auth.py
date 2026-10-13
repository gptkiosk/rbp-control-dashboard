#!/usr/bin/env python3
"""Import a downloaded web-client JSON without displaying credentials.

Run with apps/api/.venv/bin/python. Imports leave sign-in disabled unless
--enable is supplied. Existing settings are preserved; backups stay private.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from dotenv import set_key, dotenv_values
from io import StringIO
from urllib.parse import urlsplit

LOCAL = "http://127.0.0.1:8800"


def private_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 262144:
            raise ValueError("Invalid credential or settings file")
        os.fchmod(source.fileno(), 0o600)
        return source.read()


def configure(source, data_dir, enable=False, allowed_emails=None):
    document = json.loads(private_read(source))
    client = document.get("web", {})
    client_id, secret = client.get("client_id"), client.get("client_secret")
    redirects = client.get("redirect_uris", [])
    if (not isinstance(client_id, str) or not client_id.endswith(".apps.googleusercontent.com")
            or not isinstance(secret, str) or not secret.strip()
            or any(c in client_id + secret for c in "\r\n\x00")
            or not isinstance(redirects, list) or LOCAL + "/auth/callback" not in redirects):
        raise ValueError("Expected a web client with the local MCD callback")
    origins = [LOCAL]
    for redirect in redirects:
        u = urlsplit(redirect)
        if u.scheme == 'https' and u.hostname and not u.username and not u.password and u.path == '/auth/callback' and not u.query and not u.fragment:
            origin = f'{u.scheme}://{u.netloc}'
            if origin not in origins: origins.append(origin)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if data_dir.is_symlink() or data_dir.stat().st_uid != os.getuid():
        raise ValueError("Invalid settings directory")
    data_dir.chmod(0o700)
    destination = data_dir / ".env"
    existing = private_read(destination) if destination.exists() or destination.is_symlink() else b""
    prior = dotenv_values(stream=StringIO(existing.decode()), interpolate=False)
    emails = allowed_emails if allowed_emails is not None else json.loads(prior.get('MAC_CONTROL_AUTH_ALLOWED_EMAILS') or '[]')
    if not isinstance(emails, list) or any(not isinstance(email,str) or '@' not in email or any(c in email for c in '\r\n\x00') for email in emails) or (enable and not emails):
        raise ValueError('Supply allowed operator emails before enabling sign-in')
    fd, name = tempfile.mkstemp(prefix=".google-auth-", dir=data_dir)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(existing)
        values = {
            "MAC_CONTROL_GOOGLE_CLIENT_ID": client_id,
            "MAC_CONTROL_GOOGLE_CLIENT_SECRET": secret,
            "MAC_CONTROL_AUTH_ALLOWED_EMAILS": json.dumps(emails),
            "MAC_CONTROL_AUTH_ORIGINS": json.dumps(origins),
            "MAC_CONTROL_AUTH_ENABLED": "true" if enable else "false",
        }
        for key, value in values.items():
            set_key(temporary, key, value, quote_mode="always")
        temporary.chmod(0o600)
        if existing:
            backup_fd, _ = tempfile.mkstemp(prefix=f".env.before-google-auth-{int(time.time())}-", dir=data_dir)
            with os.fdopen(backup_fd, "wb") as backup:
                backup.write(existing)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".mac-control")
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--allowed-email", action="append", help="Allowed operator email; repeat for multiple accounts")
    args = parser.parse_args()
    try:
        origins = configure(args.source, args.data_dir, args.enable, args.allowed_email)
    except Exception:
        print("Import failed. Check the web-client JSON, local callback and file ownership; credentials were not displayed.")
        return 1
    print(f"Credentials imported privately; sign-in {'enabled' if args.enable else 'disabled'}. Restart MCD to apply.")
    print("Configured addresses: " + ", ".join(origins))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
