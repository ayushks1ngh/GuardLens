"""Stage 4.1: read-only and expiring tokens, an audit log with no secrets in it, per-account throttling."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from guardlens import auth
from guardlens.app import app
from guardlens.events import ApiToken, AuditLog, AuthSession, User, get_engine, utcnow

PASSWORD = "correct horse battery"


@pytest.fixture
def client():
    def wipe():
        with Session(get_engine()) as session:
            for model in (ApiToken, AuthSession, User, AuditLog):
                session.exec(delete(model))
            session.commit()
        auth.auth_state.set_enabled(False)
        auth.auth_state.limiter = auth.LoginLimiter()
        auth.auth_state.account_limiter = auth.LoginLimiter(limit=10, window=300.0)

    with TestClient(app) as c:
        wipe()
        yield c
        wipe()


def _signed_in(client):
    assert client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD}).status_code == 201
    return client


def _token(client, **body):
    r = client.post("/api/auth/tokens", json={"name": "t", **body})
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_read_token_can_look_but_not_change_or_manage(client):
    _signed_in(client)
    read = _token(client, scope="read")["token"]
    anonymous = TestClient(app)
    assert anonymous.get("/api/cameras", headers=_bearer(read)).status_code == 200
    for method, path in (("post", "/api/cameras"), ("put", "/api/auth/settings"), ("delete", "/api/events/1"), ("patch", "/api/cameras/1")):
        r = anonymous.request(method.upper(), path, headers=_bearer(read), json={})
        assert r.status_code == 403 and "read-only" in r.json()["detail"], (method, path, r.status_code)
    for path in ("/api/auth/tokens", "/api/auth/audit"):  # even reading the account's own secrets-adjacent data is refused
        assert anonymous.get(path, headers=_bearer(read)).status_code == 403
    assert anonymous.post("/api/auth/tokens", headers=_bearer(read), json={"name": "sneaky", "scope": "full"}).status_code == 403
    full = _token(client, scope="full")["token"]
    assert anonymous.get("/api/auth/tokens", headers=_bearer(full)).status_code == 200


def test_default_token_scope_is_full_so_existing_scripts_keep_working(client):
    _signed_in(client)
    assert _token(client)["scope"] == "full"
    assert client.post("/api/auth/tokens", json={"name": "x", "scope": "admin"}).status_code == 422
    assert client.post("/api/auth/tokens", json={"name": "x", "expires_days": 0}).status_code == 422


def test_expired_token_stops_working_but_stays_listed_so_it_can_be_removed(client):
    _signed_in(client)
    made = _token(client, expires_days=30)
    assert made["expires_at"]
    anonymous = TestClient(app)
    assert anonymous.get("/api/cameras", headers=_bearer(made["token"])).status_code == 200
    with Session(get_engine()) as session:
        row = session.get(ApiToken, made["id"]); row.expires_at = utcnow() - timedelta(minutes=1); session.add(row); session.commit()
    assert anonymous.get("/api/cameras", headers=_bearer(made["token"])).status_code == 401
    listed = client.get("/api/auth/tokens").json()
    assert listed[0]["expired"] is True and listed[0]["scope"] == "full"
    assert client.delete(f"/api/auth/tokens/{made['id']}").status_code == 200


def test_audit_log_records_the_story_and_never_a_secret(client):
    _signed_in(client)
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-1"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "ghost", "password": "whatever-123"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 200
    token = _token(client, name="home-assistant", scope="read", expires_days=90)
    client.delete(f"/api/auth/tokens/{token['id']}")
    client.put("/api/auth/password", json={"current": PASSWORD, "new": "another long password"})
    client.put("/api/auth/settings", json={"enabled": False})
    client.post("/api/auth/logout")
    log = client.get("/api/auth/audit")
    assert log.status_code == 401  # logged out now; sign back in to read it
    client.post("/api/auth/login", json={"username": "admin", "password": "another long password"})
    rows = client.get("/api/auth/audit").json()
    kinds = [r["kind"] for r in rows]
    for expected in ("setup", "login_failed", "login_ok", "token_created", "token_deleted", "password_changed", "login_toggled", "logout"):
        assert expected in kinds, (expected, kinds)
    assert rows[0]["kind"] == "login_ok"  # newest first
    failed = [r for r in rows if r["kind"] == "login_failed"]
    assert {r["username"] for r in failed} == {"admin", "ghost"} and all(r["ip"] for r in failed)
    created = next(r for r in rows if r["kind"] == "token_created")
    assert "home-assistant" in created["detail"] and "read" in created["detail"] and "90 days" in created["detail"]
    dump = str(rows)
    for secret in (PASSWORD, "another long password", "wrong-password-1", "whatever-123", token["token"]):
        assert secret not in dump


def test_one_account_cannot_be_hammered_from_many_addresses(client):
    _signed_in(client)
    auth.auth_state.limiter = auth.LoginLimiter(limit=10_000)  # isolate the per-account throttle from the per-address one
    attacker = TestClient(app)
    codes = [attacker.post("/api/auth/login", json={"username": "admin", "password": f"guess-number-{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert TestClient(app).post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 429  # even the right one waits
    assert TestClient(app).post("/api/auth/login", json={"username": "someone-else", "password": "x" * 12}).status_code == 401  # other names unaffected
    with Session(get_engine()) as session:  # a blocked flood does not flood the log
        assert len(session.exec(select(AuditLog).where(AuditLog.kind == "login_failed")).all()) == 11


def test_audit_log_is_pruned_by_age_and_size(client):
    with Session(get_engine()) as session:
        session.add(AuditLog(kind="login_ok", at=utcnow() - timedelta(days=400)))
        session.add(AuditLog(kind="login_ok")); session.commit()
    assert auth.prune_audit() == 1
    old_max = auth.AUDIT_MAX_ROWS
    auth.AUDIT_MAX_ROWS = 3
    try:
        with Session(get_engine()) as session:
            for _ in range(6):
                session.add(AuditLog(kind="logout"))
            session.commit()
        auth.prune_audit()
        with Session(get_engine()) as session:
            assert len(session.exec(select(AuditLog)).all()) == 3
    finally:
        auth.AUDIT_MAX_ROWS = old_max


def test_old_database_gets_the_new_token_columns_and_old_tokens_stay_full_access(tmp_path):
    from guardlens.events.models import init_engine
    path = tmp_path / "old.db"
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR NOT NULL, password_hash VARCHAR NOT NULL, created_at DATETIME NOT NULL)")
    c.execute("CREATE TABLE apitoken (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, token_hash VARCHAR NOT NULL, user_id INTEGER NOT NULL, "
              "created_at DATETIME NOT NULL, last_used_at DATETIME)")
    c.execute("INSERT INTO apitoken VALUES (1, 'old script', 'abc', 1, '2026-01-01 00:00:00', NULL)")
    c.commit(); c.close()
    engine = init_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        row = session.exec(select(ApiToken)).one()
        assert row.scope == "full" and row.expires_at is None  # nothing existing becomes weaker or expires
