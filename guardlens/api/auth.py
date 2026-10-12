"""Auth API: setup, login/logout, password, API tokens, on/off switch."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from guardlens import auth
from guardlens.events import ApiToken, AuthSession, User, get_engine
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


class SettingsBody(BaseModel):
    enabled: bool


def _current_user(request: Request) -> Optional[User]:
    return auth.authenticate(request.headers, request.cookies)


def _require_user(request: Request) -> User:
    user = getattr(request.state, "user", None) or _current_user(request)
    if user is None:
        raise HTTPException(401, "login required")
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
    _set_cookie(request, response, auth.create_session(user_id))
    return {"username": body.username.strip()}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    key = auth.client_key(request)
    if auth.auth_state.limiter.blocked(key):
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    with Session(get_engine()) as session:
        user = session.exec(select(User).where(User.username == body.username.strip())).first()
    # Verify against a dummy hash when the user is unknown so timing does not reveal usernames.
    stored = user.password_hash if user else auth.hash_password("not-a-real-password")
    if not (auth.verify_password(body.password, stored) and user):
        auth.auth_state.limiter.fail(key)
        raise HTTPException(401, "Wrong username or password.")
    auth.auth_state.limiter.reset(key)
    _set_cookie(request, response, auth.create_session(user.id))
    return {"username": user.username}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
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
    return {"ok": True}


@router.get("/tokens")
def list_tokens(request: Request):
    user = _require_user(request)
    with Session(get_engine()) as session:
        rows = session.exec(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)).all()
    return [{"id": r.id, "name": r.name, "created_at": r.created_at.isoformat(),
             "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None} for r in rows]


@router.post("/tokens", status_code=201)
def create_token(body: TokenBody, request: Request):
    user = _require_user(request)
    token = auth.new_token("glt_")
    with Session(get_engine()) as session:
        row = ApiToken(name=body.name.strip(), token_hash=auth.token_hash(token), user_id=user.id)
        session.add(row); session.commit(); session.refresh(row)
    return {"id": row.id, "name": row.name, "token": token}


@router.delete("/tokens/{token_id}")
def delete_token(token_id: int, request: Request):
    user = _require_user(request)
    with Session(get_engine()) as session:
        row = session.get(ApiToken, token_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(404, "token not found")
        session.delete(row); session.commit()
    return {"ok": True}


@router.put("/settings")
def settings(body: SettingsBody, request: Request):
    if body.enabled and not auth.auth_state.has_users():
        raise HTTPException(409, "Create the administrator account first.")
    if auth.auth_state.enabled:
        _require_user(request)
    auth.auth_state.set_enabled(body.enabled)
    return {"enabled": auth.auth_state.enabled}
