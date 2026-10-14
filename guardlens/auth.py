"""Login for the dashboard and API (docs/13 M5).

One administrator account protects every API, stream and snapshot once login is turned on.
Browsers sign in and receive an HttpOnly cookie; scripts use ``Authorization: Bearer`` API
tokens. Only hashes are stored (scrypt for passwords, SHA-256 for random tokens). Login is
off by default so existing local setups keep working; enable it before exposing GuardLens
beyond this machine (the Security page does this when the admin account is created).

Lockout recovery: start the server with GUARDLENS_AUTH_DISABLE=1 to bypass login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from guardlens.events import ApiToken, AuditLog, AuthSession, Setting, User, get_engine, utcnow

COOKIE = "gl_session"
SESSION_DAYS = 14
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
PUBLIC_EXACT = {
    "/", "/healthz", "/health", "/publish", "/favicon.ico", "/api/auth/status", "/api/auth/login",
    "/api/auth/setup", "/api/auth/logout", "/api/pairing/offer", "/api/client-log",
}
PUBLIC_PREFIX = ("/app",)  # the built dashboard itself (it needs to load to show the login screen)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt${n}${r}${p}${s}${h}".format(
        **_SCRYPT, s=base64.b64encode(salt).decode(), h=base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def password_problems(username: str, password: str) -> list[dict]:
    problems = []
    if not 3 <= len(username.strip()) <= 40:
        problems.append({"field": "username", "message": "Username must be 3 to 40 characters"})
    if len(password) < 10:
        problems.append({"field": "password", "message": "Password must be at least 10 characters"})
    if password.lower() == username.strip().lower():
        problems.append({"field": "password", "message": "Password must not match the username"})
    return problems


class LoginLimiter:
    """At most ``limit`` failed logins per client per window."""

    def __init__(self, limit: int = 5, window: float = 60.0, max_keys: int = 10_000) -> None:
        self.limit, self.window, self.max_keys = limit, window, max_keys
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.time()

    def _sweep(self, now: float) -> None:
        """Drop every key whose failures have all aged out (a name tried once and never again would otherwise stay forever)."""
        if now - self._last_sweep < self.window / 2:
            return
        self._last_sweep = now
        for key in [k for k, q in self._fails.items() if not q or now - q[-1] > self.window]:
            self._fails.pop(key, None)

    def _trim(self, key: str, now: float) -> deque:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:  # forget names nobody is failing for any more: keys are attacker-chosen, so memory must not grow
            self._fails.pop(key, None)
            return deque()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            now = time.time()
            self._sweep(now)
            return len(self._trim(key, now)) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.time()
            self._sweep(now)
            self._trim(key, now)
            if len(self._fails) >= self.max_keys:  # hard cap: drop the oldest key
                self._fails.pop(next(iter(self._fails)), None)
            self._fails[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


class AuthState:
    def __init__(self) -> None:
        self._enabled = False
        self.setup_code: Optional[str] = None
        self.setup_lock = threading.Lock()  # account creation is check-then-insert: make it one step
        self.limiter = LoginLimiter()                                  # per client address: 5 failures / minute
        self.account_limiter = LoginLimiter(limit=10, window=300.0)    # per account name: 10 failures / 5 minutes, from anywhere

    def load(self) -> None:
        with Session(get_engine()) as session:
            row = session.get(Setting, "auth")
        self._enabled = bool(row and (row.value or {}).get("enabled"))

    @property
    def enabled(self) -> bool:
        return self._enabled and os.environ.get("GUARDLENS_AUTH_DISABLE") != "1"

    def set_enabled(self, value: bool) -> None:
        with Session(get_engine()) as session:
            row = session.get(Setting, "auth") or Setting(key="auth")
            row.value = {"enabled": bool(value)}
            session.add(row)
            session.commit()
        self._enabled = bool(value)

    def ensure_setup_code(self) -> str:
        """One-time code that proves the person creating the first account can read this server's log/terminal."""
        if self.setup_code is None:
            alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
            raw = "".join(secrets.choice(alphabet) for _ in range(8))
            self.setup_code = f"{raw[:4]}-{raw[4:]}"
        return self.setup_code

    @staticmethod
    def has_users() -> bool:
        with Session(get_engine()) as session:
            return session.exec(select(User.id).limit(1)).first() is not None


auth_state = AuthState()


_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "cf-connecting-ip", "x-real-ip", "tailscale-user-login")


def arrived_through_proxy(headers) -> bool:
    """True when a reverse proxy or tunnel (Cloudflare, Tailscale, nginx...) relayed the request."""
    return any(headers.get(name) for name in _PROXY_HEADERS)


def is_public(path: str, method: str) -> bool:
    if method == "OPTIONS" or path in PUBLIC_EXACT:
        return True
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIX)


def create_session(user_id: int) -> str:
    token = new_token()
    with Session(get_engine()) as session:
        session.add(AuthSession(token_hash=token_hash(token), user_id=user_id,
                                expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
        session.commit()
    return token


def user_from_cookie(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    with Session(get_engine()) as session:
        row = session.exec(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).first()
        if row is None:
            return None
        if row.expires_at.replace(tzinfo=None) < utcnow().replace(tzinfo=None):  # SQLite returns naive datetimes
            session.delete(row); session.commit()
            return None
        return session.get(User, row.user_id)


def _bearer(header: Optional[str]) -> Optional[tuple[User, str]]:
    """(user, scope) for a valid, unexpired bearer token; None otherwise."""
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    with Session(get_engine()) as session:
        row = session.exec(select(ApiToken).where(ApiToken.token_hash == token_hash(token))).first()
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at.replace(tzinfo=None) < utcnow().replace(tzinfo=None):
            return None  # expired (kept in the list so it can be seen and deleted)
        row.last_used_at = utcnow()
        session.add(row); session.commit()
        user = session.get(User, row.user_id)
        return (user, row.scope or "full") if user else None


def user_from_bearer(header: Optional[str]) -> Optional[User]:
    found = _bearer(header)
    return found[0] if found else None


SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def identify(headers, cookies) -> Optional[tuple[User, str]]:
    """Who is calling and with what rights: a signed-in browser is "full"; an API token is "read" or "full"."""
    found = _bearer(headers.get("authorization"))
    if found:
        return found
    user = user_from_cookie(cookies.get(COOKIE))
    return (user, "full") if user else None


def authenticate(headers, cookies) -> Optional[User]:
    found = identify(headers, cookies)
    return found[0] if found else None


def client_key(request) -> str:
    return request.client.host if request.client else "unknown"


# -- audit log ------------------------------------------------------------------------------------------------------
AUDIT_KEEP_DAYS = 180
AUDIT_MAX_ROWS = 10_000


def audit(kind: str, *, username: Optional[str] = None, request=None, detail: str = "") -> None:
    """Record a security-relevant event. Never raises: auditing must not break the action being audited."""
    try:
        with Session(get_engine()) as session:
            session.add(AuditLog(kind=kind, username=(username or None), ip=client_key(request) if request is not None else None,
                                 detail=detail[:200]))
            session.commit()
    except Exception:  # pragma: no cover - logged, not fatal
        import logging
        logging.getLogger("guardlens.auth").exception("could not write audit entry %s", kind)


def prune_audit(days: int = AUDIT_KEEP_DAYS) -> int:
    from datetime import timedelta
    cutoff = utcnow().replace(tzinfo=None) - timedelta(days=days)
    with Session(get_engine()) as session:
        old = session.exec(select(AuditLog).where(AuditLog.at < cutoff)).all()
        for row in old:
            session.delete(row)
        removed = len(old)
        extra = session.exec(select(AuditLog).order_by(AuditLog.at.desc()).offset(AUDIT_MAX_ROWS)).all()  # hard cap
        for row in extra:
            session.delete(row)
        session.commit()
        return removed + len(extra)


def full_access_or_open(headers, cookies) -> Optional[str]:
    """None when allowed; otherwise a refusal message. With login off everything is open; with login on, read-only tokens
    may not use the caller (used for endpoints that expose secrets, such as database backups)."""
    if not auth_state.enabled:
        return None
    found = identify(headers, cookies)
    if found is None:
        return "login required"
    return None if found[1] == "full" else "This token is read-only."


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}  # "testclient" only ever comes from Starlette's TestClient


def setup_code_required(request) -> bool:
    """First-run account creation from another machine (or through a proxy) needs the code from the server log."""
    if auth_state.has_users():
        return False
    return client_key(request) not in LOOPBACK_HOSTS or arrived_through_proxy(request.headers)


def setup_code_matches(given: Optional[str]) -> bool:
    if not given or auth_state.setup_code is None:
        return False
    normal = lambda text: text.replace("-", "").replace(" ", "").strip().upper()
    return hmac.compare_digest(normal(given).encode(), normal(auth_state.setup_code).encode())
