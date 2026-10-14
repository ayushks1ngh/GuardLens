"""Findings from the independent security review (2026-10-14): each test fails on the code before its fix."""
from __future__ import annotations

import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select
from starlette.websockets import WebSocketDisconnect

from guardlens import auth, maintenance
from guardlens.app import app
from guardlens.events import ApiToken, AuditLog, AuthSession, Person, User, get_engine

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
        auth.auth_state.setup_code = None

    with TestClient(app) as c:
        wipe()
        yield c
        wipe()


def _admin(client):
    assert client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD}).status_code == 201


def _token(client, scope):
    return client.post("/api/auth/tokens", json={"name": "t", "scope": scope}).json()["token"]


# 1. HIGH: the WebSocket bypassed login --------------------------------------------------------------------------------
def test_overlay_websocket_needs_login_when_login_is_on(client):
    with client.websocket_connect("/ws/overlay") as ws:  # login off: still open, as before
        assert isinstance(ws.receive_json(), dict)
    _admin(client)
    stranger = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as refused:
        with stranger.websocket_connect("/ws/overlay") as ws:
            ws.receive_json()
    assert refused.value.code == 1008
    token = _token(client, "read")
    with stranger.websocket_connect("/ws/overlay", headers={"Authorization": f"Bearer {token}"}) as ws:  # looking is allowed
        assert isinstance(ws.receive_json(), dict)
    with client.websocket_connect("/ws/overlay") as ws:  # a signed-in browser (cookie) works
        assert isinstance(ws.receive_json(), dict)


# 2. MEDIUM: a read-only token could download the whole database ---------------------------------------------------------
def test_read_only_tokens_cannot_touch_backups_or_storage_info(client):
    _admin(client)
    name = client.post("/api/data/backups").json()["name"]
    read = {"Authorization": f"Bearer {_token(client, 'read')}"}
    anonymous = TestClient(app)
    for path in ("/api/data/status", f"/api/data/backups/{name}"):
        r = anonymous.get(path, headers=read)
        assert r.status_code == 403 and "read-only" in r.json()["detail"].lower(), path
    full = {"Authorization": f"Bearer {_token(client, 'full')}"}
    assert anonymous.get(f"/api/data/backups/{name}", headers=full).content[:15] == b"SQLite format 3"
    assert client.get("/api/data/status").status_code == 200


# 3. an anonymous caller could lock the real administrator out ----------------------------------------------------------
def test_guessing_from_one_address_does_not_lock_the_admin_out_from_another(client):
    _admin(client)
    auth.auth_state.limiter = auth.LoginLimiter(limit=10_000)
    attacker = TestClient(app, client=("198.51.100.9", 5000))
    codes = [attacker.post("/api/auth/login", json={"username": "admin", "password": f"guess-{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]          # the attacker's address is slowed down...
    owner = TestClient(app, client=("192.0.2.10", 5000))
    assert owner.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 200  # ...the owner is not


def test_limiter_forgets_empty_keys_and_caps_memory():
    limiter = auth.LoginLimiter(limit=3, window=0.01)
    for i in range(50):
        limiter.fail(f"name-{i}")
    import time; time.sleep(0.05)
    limiter.blocked("anything")  # trimming happens on use
    assert len(limiter._fails) <= 1
    capped = auth.LoginLimiter(limit=3, window=60.0, max_keys=100)
    for i in range(500):
        capped.fail(f"k{i}")
    assert len(capped._fails) <= 100


# 6. a password typed into the username box must not be kept ------------------------------------------------------------
def test_unknown_usernames_are_not_stored_in_the_audit_log(client):
    _admin(client)
    TestClient(app).post("/api/auth/login", json={"username": "my-secret-password-1", "password": "x" * 12})
    TestClient(app).post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    rows = client.get("/api/auth/audit").json()
    failed = [r for r in rows if r["kind"] == "login_failed"]
    assert len(failed) == 2 and "my-secret-password-1" not in str(rows)
    assert {r["username"] for r in failed} == {"admin", None}


# 5. client-log: terminal control characters and per-address limits ----------------------------------------------------
def test_client_log_strips_control_characters_and_limits_each_address(client, caplog):
    with caplog.at_level("ERROR", logger="guardlens.client"):
        client.post("/api/client-log", json={"message": "\x1b[2J\x1b[31mCLEARED\x07", "page": "/p", "agent": "ua"})
    line = caplog.records[0].getMessage()
    assert "\x1b" not in line and "\x07" not in line and "CLEARED" in line
    from guardlens.api import clientlog
    clientlog._recent.clear()
    noisy = TestClient(app, client=("203.0.113.5", 1))
    for _ in range(30):
        noisy.post("/api/client-log", json={"message": "spam"})
    quiet = TestClient(app, client=("203.0.113.6", 1))
    with caplog.at_level("ERROR", logger="guardlens.client"):
        caplog.clear()
        quiet.post("/api/client-log", json={"message": "real crash"})
    assert any("real crash" in r.getMessage() for r in caplog.records)  # one address cannot silence another
    assert client.post("/api/client-log", content=b"{" + b" " * 50_000 + b"}", headers={"content-type": "application/json"}).status_code in (413, 422)


# 7. image uploads: bounded reads, decompression-bomb check --------------------------------------------------------------
def test_face_upload_rejects_oversized_and_absurd_canvas_images(client):
    with Session(get_engine()) as session:
        person = Person(name="Upload test", watchlist=False); session.add(person); session.commit(); session.refresh(person)
    big = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (60000).to_bytes(4, "big") + (60000).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00" + b"0" * 64
    r = client.post(f"/api/persons/{person.id}/images", files={"image": ("bomb.png", big, "image/png")})
    assert r.status_code == 413 and "dimensions" in r.json()["detail"]
    r = client.post(f"/api/persons/{person.id}/images", files={"image": ("huge.jpg", b"0" * (11 * 1024 * 1024), "image/jpeg")})
    assert r.status_code == 413
    ok, buf = cv2.imencode(".jpg", np.full((120, 120, 3), 128, np.uint8))
    assert client.post(f"/api/persons/{person.id}/images", files={"image": ("ok.jpg", buf.tobytes(), "image/jpeg")}).status_code == 201


def test_backup_names_with_a_trailing_newline_are_not_accepted():
    assert maintenance.BACKUP_NAME.fullmatch("guardlens-manual-20261014-205346.db")
    assert not maintenance.BACKUP_NAME.fullmatch("guardlens-manual-20261014-205346.db\n")


# 4. first-run takeover ------------------------------------------------------------------------------------------------
def test_creating_the_first_account_from_another_computer_needs_the_setup_code(client):
    lan = TestClient(app, client=("192.168.1.50", 40000))
    assert lan.get("/api/auth/status").json()["setup_code_required"] is True
    assert client.get("/api/auth/status").json()["setup_code_required"] is False  # this computer: not asked
    code = auth.auth_state.ensure_setup_code()
    body = {"username": "mallory", "password": PASSWORD}
    for bad in ({}, {"setup_code": "WRONG-CODE"}):
        r = lan.post("/api/auth/setup", json={**body, **bad})
        assert r.status_code == 403 and "setup code" in r.json()["detail"].lower()
    assert lan.get("/api/auth/status").json()["needs_setup"] is True  # still nobody is admin
    ok = lan.post("/api/auth/setup", json={**body, "username": "owner", "setup_code": code.lower().replace("-", " ")})  # forgiving format
    assert ok.status_code == 201 and auth.auth_state.setup_code is None  # one use only
    assert lan.post("/api/auth/setup", json={**body, "setup_code": code}).status_code == 409


def test_guessing_the_setup_code_is_rate_limited(client):
    lan = TestClient(app, client=("192.168.1.51", 40000))
    auth.auth_state.ensure_setup_code()
    codes = [lan.post("/api/auth/setup", json={"username": "x" * 5, "password": PASSWORD, "setup_code": f"AAAA-{i:04d}"}).status_code for i in range(7)]
    assert codes[:5] == [403] * 5 and codes[5:] == [429, 429]


def test_two_simultaneous_first_setups_create_exactly_one_administrator(client):
    import threading
    results = []
    def attempt(name):
        results.append(TestClient(app).post("/api/auth/setup", json={"username": name, "password": PASSWORD}).status_code)
    threads = [threading.Thread(target=attempt, args=(f"admin{i}",)) for i in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sorted(results) == [201] + [409] * 5
    with Session(get_engine()) as session:
        assert len(session.exec(select(User)).all()) == 1


def test_peek_dimensions_reads_png_and_jpeg_headers():
    from guardlens.api.faces import peek_dimensions
    ok, jpg = cv2.imencode(".jpg", np.zeros((70, 130, 3), np.uint8))
    ok2, png = cv2.imencode(".png", np.zeros((50, 90, 3), np.uint8))
    assert peek_dimensions(jpg.tobytes()) == (130, 70) and peek_dimensions(png.tobytes()) == (90, 50)
    assert peek_dimensions(b"GIF89a") is None and peek_dimensions(b"") is None
