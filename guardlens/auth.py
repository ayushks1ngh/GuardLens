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

from guardlens.events import ApiToken, AuthSession, Setting, User, get_engine, utcnow

COOKIE = "gl_session"
SESSION_DAYS = 14
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
PUBLIC_EXACT = {
    "/", "/classic", "/healthz", "/health", "/publish", "/favicon.ico", "/api/auth/status", "/api/auth/login",
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

    def __init__(self, limit: int = 5, window: float = 60.0) -> None:
        self.limit, self.window = limit, window
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._trim(key, time.time())) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._trim(key, time.time()).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


class AuthState:
    def __init__(self) -> None:
        self._enabled = False
        self.limiter = LoginLimiter()

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

    @staticmethod
    def has_users() -> bool:
        with Session(get_engine()) as session:
            return session.exec(select(User.id).limit(1)).first() is not None


auth_state = AuthState()


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


def user_from_bearer(header: Optional[str]) -> Optional[User]:
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    with Session(get_engine()) as session:
        row = session.exec(select(ApiToken).where(ApiToken.token_hash == token_hash(token))).first()
        if row is None:
            return None
        row.last_used_at = utcnow()
        session.add(row); session.commit()
        return session.get(User, row.user_id)


def authenticate(headers, cookies) -> Optional[User]:
    return user_from_bearer(headers.get("authorization")) or user_from_cookie(cookies.get(COOKIE))


def client_key(request) -> str:
    return request.client.host if request.client else "unknown"
