"""Google authorization-code login and revocable, origin-bound local sessions."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import stat
import time
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import HTTPException, Request
from sqlalchemy import delete
from models import AuthSession

SESSION_SECONDS = 12 * 3600
FLOW_SECONDS = 300
GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_KEYS = "https://www.googleapis.com/oauth2/v3/certs"
PAGES = {"/", "/mac", "/services", "/tasks", "/agents", "/chat", "/mcp", "/github", "/reports"}
PUBLIC = {"/healthz", "/login", "/auth/status", "/auth/login", "/auth/callback", "/auth/recover", "/favicon.svg", "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png"}


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def safe_next(value):
    try:
        u = urlsplit(value)
    except ValueError:
        return "/"
    return value if u.path in PAGES and not u.scheme and not u.netloc and not u.fragment and "\\" not in value and not any(ord(c) < 32 for c in value) else "/"


def loopback(host):
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def cookie_name(origin, flow=False):
    prefix = "__Host-" if origin.startswith("https://") else ""
    return prefix + ("mcd_login" if flow else "mcd_session")


def cookie(response, origin, value, *, flow=False, age=SESSION_SECONDS):
    response.set_cookie(cookie_name(origin, flow), value, max_age=age, path="/", httponly=True,
                        secure=origin.startswith("https://"), samesite="lax")


def clear_cookie(response, origin, flow=False):
    response.delete_cookie(cookie_name(origin, flow), path="/", httponly=True,
                           secure=origin.startswith("https://"), samesite="lax")


class GoogleProvider:
    def __init__(self, settings):
        self.settings = settings
        self.keys = {}
        self.keys_until = 0

    async def exchange(self, code, verifier, redirect_uri):
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.post(GOOGLE_TOKEN, data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret.get_secret_value(),
                "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"})
            response.raise_for_status()
            token = response.json().get("id_token")
            if not isinstance(token, str) or len(token) > 16000:
                raise ValueError("Missing ID token")
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or len(kid) > 100:
                raise ValueError("Invalid signing key")
            if time.time() >= self.keys_until or kid not in self.keys:
                response = await client.get(GOOGLE_KEYS)
                response.raise_for_status()
                self.keys = {k["kid"]: jwt.PyJWK.from_dict(k).key for k in response.json()["keys"]
                             if k.get("kty") == "RSA" and k.get("alg", "RS256") == "RS256" and k.get("use", "sig") == "sig"}
                self.keys_until = time.time() + 3600
            return verify_id_token(token, self.keys.get(kid), self.settings.google_client_id)


def verify_id_token(token, key, client_id):
    if key is None:
        raise ValueError("Unknown signing key")
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id,
                        issuer=["https://accounts.google.com", "accounts.google.com"], leeway=30,
                        options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce", "email", "email_verified"]})
    if claims.get("azp", client_id) != client_id:
        raise ValueError("Wrong authorized party")
    if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
        raise ValueError("Missing authorized party")
    return claims


class AuthService:
    def __init__(self, settings, sessions, provider=None, clock=time.time):
        self.settings = settings
        self.sessions = sessions
        self.provider = provider or GoogleProvider(settings)
        self.clock = clock
        self.flows = {}
        self.recovery_attempts = []
        self.recovery_hash = None
        if settings.auth_enabled:
            path = settings.data_dir / "admin-recovery-token"
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_urlsafe(48) + "\n")
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("Recovery token must be a regular file owned by this Mac user, mode 600")
            token = path.read_text().strip()
            if len(token) < 40:
                raise ValueError("Invalid recovery token file")
            self.recovery_hash = digest(token)

    def origin(self, request):
        host = request.headers.get("host", "")
        for origin in self.settings.auth_origins:
            if urlsplit(origin).netloc == host:
                if loopback(urlsplit(origin).hostname or "") and not loopback(request.client.host if request.client else ""):
                    raise HTTPException(403, "Loopback sign-in requires a local connection.")
                if origin.startswith("https://") and request.url.scheme != "https" and not loopback(request.client.host if request.client else ""):
                    raise HTTPException(403, "HTTPS is required for this address.")
                return origin
        raise HTTPException(403, "This address is not configured for sign-in.")

    def current(self, request):
        if not self.settings.auth_enabled:
            return None
        origin = self.origin(request)
        token = request.cookies.get(cookie_name(origin), "")
        if not token or len(token) > 128:
            return None
        with self.sessions() as s:
            row = s.get(AuthSession, digest(token))
            if not row or row.origin != origin or row.expires_at <= self.clock():
                return None
            if row.method == "google" and row.email not in {x.lower() for x in self.settings.auth_allowed_emails}:
                return None
            return {"email": row.email, "method": row.method, "expires_at": row.expires_at}

    def issue(self, origin, email, subject, method, request):
        token = secrets.token_urlsafe(48)
        with self.sessions.begin() as s:
            s.execute(delete(AuthSession).where(AuthSession.expires_at <= self.clock()))
            previous = request.cookies.get(cookie_name(origin), "")
            if previous:
                s.execute(delete(AuthSession).where(AuthSession.token_hash == digest(previous)))
            s.add(AuthSession(token_hash=digest(token), origin=origin, email=email, subject=subject,
                              method=method, expires_at=int(self.clock() + SESSION_SECONDS)))
        return token

    def begin(self, request, next_path):
        origin = self.origin(request)
        now = self.clock()
        self.flows = {k: v for k, v in self.flows.items() if v["expires"] > now}
        if len(self.flows) >= 64:
            raise HTTPException(429, "Too many sign-in attempts. Try again shortly.")
        state, binding, nonce, verifier = (secrets.token_urlsafe(n) for n in (32, 32, 32, 48))
        self.flows[state] = {"binding": digest(binding), "nonce": nonce, "verifier": verifier,
                             "origin": origin, "next": safe_next(next_path), "expires": now + FLOW_SECONDS}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        url = GOOGLE_AUTHORIZE + "?" + urlencode({"client_id": self.settings.google_client_id,
            "redirect_uri": origin + "/auth/callback", "response_type": "code", "scope": "openid email",
            "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
            "prompt": "select_account"})
        return url, binding, origin

    async def finish(self, request, state, code):
        origin = self.origin(request)
        flow = self.flows.get(state)
        binding = request.cookies.get(cookie_name(origin, True), "")
        if not flow or flow["expires"] <= self.clock() or flow["origin"] != origin or not binding or not hmac.compare_digest(flow["binding"], digest(binding)):
            raise ValueError("Invalid login attempt")
        del self.flows[state]  # Consume once, including provider/allowlist failures.
        if not code:
            raise ValueError("Login cancelled")
        claims = await self.provider.exchange(code, flow["verifier"], origin + "/auth/callback")
        nonce = claims.get("nonce")
        email, sub = claims.get("email"), claims.get("sub")
        if (not isinstance(nonce, str) or not hmac.compare_digest(nonce, flow["nonce"])
                or claims.get("email_verified") is not True or not isinstance(email, str)
                or len(email) > 255 or not isinstance(sub, str) or not sub or len(sub) > 255
                or email.lower() not in {x.lower() for x in self.settings.auth_allowed_emails}):
            raise ValueError("Account refused")
        return self.issue(origin, email.lower(), sub, "google", request), flow["next"], origin

    def local_recovery_allowed(self, request):
        return (request.client is not None and loopback(request.client.host)
                and loopback(request.url.hostname or "")
                and not any(k.lower() in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto") for k in request.headers))

    def recover(self, request, token):
        if not self.local_recovery_allowed(request):
            raise HTTPException(403, "Recovery is available only directly on this Mac.")
        now = self.clock()
        self.recovery_attempts = [t for t in self.recovery_attempts if t > now - 60]
        if len(self.recovery_attempts) >= 5:
            raise HTTPException(429, "Too many recovery attempts. Try again in a minute.")
        self.recovery_attempts.append(now)
        if not self.recovery_hash or not hmac.compare_digest(self.recovery_hash, digest(token)):
            raise HTTPException(401, "Recovery token refused.")
        origin = self.origin(request)
        return self.issue(origin, "Local administrator", "local", "recovery", request), origin

    def logout(self, request):
        origin = self.origin(request)
        token = request.cookies.get(cookie_name(origin), "")
        with self.sessions.begin() as s:
            s.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
        return origin
