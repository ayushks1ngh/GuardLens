"""Auth API: setup, login/logout, password, API tokens, on/off switch."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from guardlens import auth
from guardlens.events import ApiToken, AuditLog, AuthSession, User, get_engine, utcnow
from guardlens.schema import error_detail

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)


class PasswordBody(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["read", "full"] = "full"
    expires_days: Optional[int] = Field(default=None, ge=1, le=3650)


class SettingsBody(BaseModel):
    enabled: bool


def _current_user(request: Request) -> Optional[User]:
    return auth.authenticate(request.headers, request.cookies)


def _require_user(request: Request) -> User:
    """A signed-in browser or a full-access token. Read-only tokens may not manage the account, tokens or audit log."""
    found = auth.identify(request.headers, request.cookies)
    if found is None:
        raise HTTPException(401, "login required")
    user, scope = found
    if scope != "full":
        raise HTTPException(403, "This token is read-only.")
    return user


def _set_cookie(request: Request, response: Response, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")


@router.get("/status")
def status(request: Request):
    user = _current_user(request)
    return {"enabled": auth.auth_state.enabled, "needs_setup": not auth.auth_state.has_users(),
            "authenticated": user is not None, "username": user.username if user else None}


@router.post("/setup", status_code=201)
def setup(body: Credentials, request: Request, response: Response):
    if auth.auth_state.has_users():
        raise HTTPException(409, "An administrator account already exists.")
    problems = auth.password_problems(body.username, body.password)
    if problems:
        raise HTTPException(422, error_detail(problems))
    with Session(get_engine()) as session:
        user = User(username=body.username.strip(), password_hash=auth.hash_password(body.password))
        session.add(user); session.commit(); session.refresh(user)
        user_id = user.id
    auth.auth_state.set_enabled(True)
    auth.audit("setup", username=body.username.strip(), request=request, detail="administrator account created; login turned on")
    _set_cookie(request, response, auth.create_session(user_id))
    return {"username": body.username.strip()}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    key = auth.client_key(request)
    account = "acct:" + body.username.strip().lower()
    if auth.auth_state.limiter.blocked(key) or auth.auth_state.account_limiter.blocked(account):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    with Session(get_engine()) as session:
        user = session.exec(select(User).where(User.username == body.username.strip())).first()
    # Verify against a dummy hash when the user is unknown so timing does not reveal usernames.
    stored = user.password_hash if user else auth.hash_password("not-a-real-password")
    if not (auth.verify_password(body.password, stored) and user):
        auth.auth_state.limiter.fail(key)
        auth.auth_state.account_limiter.fail(account)
        auth.audit("login_failed", username=body.username.strip(), request=request, detail="wrong username or password")
        raise HTTPException(401, "Wrong username or password.")
    auth.auth_state.limiter.reset(key)
    auth.auth_state.account_limiter.reset(account)
    auth.audit("login_ok", username=user.username, request=request)
    _set_cookie(request, response, auth.create_session(user.id))
    return {"username": user.username}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
    who = auth.user_from_cookie(token)
    if who:
        auth.audit("logout", username=who.username, request=request)
    if token:
        with Session(get_engine()) as session:
            row = session.exec(select(AuthSession).where(AuthSession.token_hash == auth.token_hash(token))).first()
            if row:
                session.delete(row); session.commit()
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.put("/password")
def change_password(body: PasswordBody, request: Request):
    user = _require_user(request)
    if not auth.verify_password(body.current, user.password_hash):
        raise HTTPException(422, error_detail([{"field": "current", "message": "Current password is wrong"}]))
    problems = [p for p in auth.password_problems(user.username, body.new) if p["field"] == "password"]
    if problems:
        raise HTTPException(422, error_detail([{**p, "field": "new"} for p in problems]))
    with Session(get_engine()) as session:
        row = session.get(User, user.id)
        row.password_hash = auth.hash_password(body.new)
        session.add(row)
        # Sign out every other browser: a changed password invalidates existing sessions.
        keep = auth.token_hash(request.cookies.get(auth.COOKIE) or "")
        for other in session.exec(select(AuthSession).where(AuthSession.user_id == user.id)).all():
            if other.token_hash != keep:
                session.delete(other)
        session.commit()
    auth.audit("password_changed", username=user.username, request=request, detail="other sessions signed out")
    return {"ok": True}


@router.get("/tokens")
def list_tokens(request: Request):
    user = _require_user(request)
    with Session(get_engine()) as session:
        rows = session.exec(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)).all()
    now = utcnow().replace(tzinfo=None)
    return [{"id": r.id, "name": r.name, "created_at": r.created_at.isoformat(),
             "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
             "scope": r.scope or "full", "expires_at": r.expires_at.isoformat() if r.expires_at else None,
             "expired": bool(r.expires_at and r.expires_at.replace(tzinfo=None) < now)} for r in rows]


@router.post("/tokens", status_code=201)
def create_token(body: TokenBody, request: Request):
    user = _require_user(request)
    token = auth.new_token("glt_")
    with Session(get_engine()) as session:
        expires = utcnow() + timedelta(days=body.expires_days) if body.expires_days else None
        row = ApiToken(name=body.name.strip(), token_hash=auth.token_hash(token), user_id=user.id, scope=body.scope, expires_at=expires)
        session.add(row); session.commit(); session.refresh(row)
    auth.audit("token_created", username=user.username, request=request,
               detail=f"{row.name} ({row.scope}, {'expires in %d days' % body.expires_days if body.expires_days else 'never expires'})")
    return {"id": row.id, "name": row.name, "token": token, "scope": row.scope,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None}


@router.delete("/tokens/{token_id}")
def delete_token(token_id: int, request: Request):
    user = _require_user(request)
    with Session(get_engine()) as session:
        row = session.get(ApiToken, token_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(404, "token not found")
        name = row.name
        session.delete(row); session.commit()
    auth.audit("token_deleted", username=user.username, request=request, detail=name)
    return {"ok": True}


@router.get("/audit")
def audit_log(request: Request, limit: int = 50):
    """Recent sign-ins, failures and access changes, newest first (signed-in users and full-access tokens only)."""
    _require_user(request)
    with Session(get_engine()) as session:
        rows = session.exec(select(AuditLog).order_by(AuditLog.at.desc()).limit(max(1, min(limit, 200)))).all()
    return [{"id": r.id, "at": r.at.isoformat(), "kind": r.kind, "username": r.username, "ip": r.ip, "detail": r.detail} for r in rows]


@router.put("/settings")
def settings(body: SettingsBody, request: Request):
    if body.enabled and not auth.auth_state.has_users():
        raise HTTPException(409, "Create the administrator account first.")
    if auth.auth_state.enabled:
        _require_user(request)
    auth.auth_state.set_enabled(body.enabled)
    found = auth.identify(request.headers, request.cookies)
    auth.audit("login_toggled", username=found[0].username if found else None, request=request, detail="login turned " + ("on" if body.enabled else "off"))
    return {"enabled": auth.auth_state.enabled}
