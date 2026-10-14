"""M5: login, sessions, API tokens, middleware coverage, lockout protections."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from guardlens import auth
from guardlens.app import app
from guardlens.events import ApiToken, AuthSession, User, get_engine

PASSWORD = "correct horse battery"


@pytest.fixture
def client():
    """A fresh app with no users; always restores 'login off' so other tests are unaffected."""
    def wipe():
        with Session(get_engine()) as session:
            for model in (ApiToken, AuthSession, User):
                session.exec(delete(model))
            session.commit()
        auth.auth_state.set_enabled(False)
        auth.auth_state.limiter = auth.LoginLimiter()

    with TestClient(app) as c:
        wipe()
        yield c
        wipe()


def test_password_hashing_and_rules():
    stored = auth.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert auth.verify_password(PASSWORD, stored) and not auth.verify_password("nope", stored)
    assert not auth.verify_password(PASSWORD, "garbage")
    assert auth.hash_password(PASSWORD) != stored  # salted
    assert len(auth.password_problems("ab", "short")) == 2
    assert auth.password_problems("admin1", PASSWORD) == []


def test_limiter_blocks_after_limit_then_resets():
    limiter = auth.LoginLimiter(limit=3, window=60)
    for _ in range(3):
        assert not limiter.blocked("ip")
        limiter.fail("ip")
    assert limiter.blocked("ip") and not limiter.blocked("other")
    limiter.reset("ip")
    assert not limiter.blocked("ip")


def test_login_is_off_until_setup_and_everything_works_before(client):
    status = client.get("/api/auth/status").json()
    assert status == {"enabled": False, "needs_setup": True, "authenticated": False, "username": None}
    assert client.get("/api/cameras").status_code == 200  # existing local setups keep working


def test_setup_enables_login_and_protects_everything(client):
    weak = client.post("/api/auth/setup", json={"username": "admin", "password": "short"})
    assert weak.status_code == 422 and weak.json()["detail"]["errors"][0]["field"] == "password"
    ok = client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    assert ok.status_code == 201
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/cameras").status_code == 200  # setup also signed this browser in
    assert client.post("/api/auth/setup", json={"username": "x2x", "password": PASSWORD}).status_code == 409

    anonymous = TestClient(app)
    for path in ("/api/cameras", "/api/events", "/api/agents", "/api/assistant/sessions/x", "/stream/1/mjpeg",
                 "/history/anything.jpg", "/api/events/stream", "/openapi.json", "/api/rules/types"):
        method = "delete" if "sessions" in path else "get"
        assert getattr(anonymous, method)(path).status_code == 401, path
    for path in ("/", "/healthz", "/api/auth/status", "/publish", "/app/"):
        assert anonymous.get(path).status_code != 401, path
    assert anonymous.get("/health").json() == {"status": "ok"}  # minimal when signed out
    assert "cameras" in client.get("/health").json()


def test_login_logout_and_wrong_credentials(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "ghost", "password": PASSWORD}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 200
    assert other.get("/api/cameras").status_code == 200
    assert other.get("/api/auth/status").json()["username"] == "admin"
    other.post("/api/auth/logout")
    assert other.get("/api/cameras").status_code == 401


def test_repeated_failures_are_rate_limited(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    attacker = TestClient(app)
    codes = [attacker.post("/api/auth/login", json={"username": "admin", "password": f"guess-{i}-guess"}).status_code
             for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    # even the right password is refused while locked out
    assert attacker.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 429


def test_api_tokens_work_as_bearer_and_can_be_revoked(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    created = client.post("/api/auth/tokens", json={"name": "script"}).json()
    assert created["token"].startswith("glt_")
    listed = client.get("/api/auth/tokens").json()
    assert listed[0]["name"] == "script" and "token" not in listed[0] and listed[0]["last_used_at"] is None
    script = TestClient(app)
    header = {"Authorization": f"Bearer {created['token']}"}
    assert script.get("/api/cameras", headers=header).status_code == 200
    assert script.get("/api/cameras", headers={"Authorization": "Bearer glt_wrong"}).status_code == 401
    assert client.get("/api/auth/tokens").json()[0]["last_used_at"] is not None
    assert client.delete(f"/api/auth/tokens/{created['id']}").status_code == 200
    assert script.get("/api/cameras", headers=header).status_code == 401
    assert client.delete("/api/auth/tokens/99999").status_code == 404


def test_password_change_signs_out_other_browsers(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    second = TestClient(app)
    second.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert client.put("/api/auth/password", json={"current": "bad-current-pw", "new": "another long pass"}).status_code == 422
    assert client.put("/api/auth/password", json={"current": PASSWORD, "new": "short"}).status_code == 422
    assert client.put("/api/auth/password", json={"current": PASSWORD, "new": "another long pass"}).status_code == 200
    assert client.get("/api/cameras").status_code == 200   # the browser that changed it stays signed in
    assert second.get("/api/cameras").status_code == 401  # others are signed out
    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json={"username": "admin", "password": "another long pass"}).status_code == 200


def test_settings_toggle_and_break_glass(client, monkeypatch):
    assert client.put("/api/auth/settings", json={"enabled": True}).status_code == 409  # no account yet
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    anonymous = TestClient(app)
    assert anonymous.put("/api/auth/settings", json={"enabled": False}).status_code == 401
    monkeypatch.setenv("GUARDLENS_AUTH_DISABLE", "1")  # lockout recovery switch
    assert anonymous.get("/api/cameras").status_code == 200
    monkeypatch.delenv("GUARDLENS_AUTH_DISABLE")
    assert anonymous.get("/api/cameras").status_code == 401
    assert client.put("/api/auth/settings", json={"enabled": False}).json() == {"enabled": False}
    assert anonymous.get("/api/cameras").status_code == 200


def test_phone_publisher_endpoint_stays_reachable_with_its_own_token(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    response = TestClient(app).post("/api/pairing/offer", json={"stream_id": "x" * 10, "token": "t" * 40, "sdp": "v=0\r\n" * 3})
    assert response.json()["detail"] != "login required"  # rejected by its own pairing-token check, not by login
    assert TestClient(app).post("/api/pairing", json={}).status_code == 401  # creating pairings needs login


def test_dashboard_shell_loads_signed_out_so_the_login_screen_can_show(client):
    from guardlens.config import ROOT
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    anonymous = TestClient(app)
    assert anonymous.get("/api/auth/status").json() == {
        "enabled": True, "needs_setup": False, "authenticated": False, "username": None}
    assert anonymous.get("/api/cameras").status_code == 401
    if (ROOT / "frontend-app" / "dist" / "index.html").exists():
        page = anonymous.get("/app/")
        assert page.status_code == 200 and '<div id="root">' in page.text
        assert page.headers["cache-control"] == "no-cache"  # never serve a stale entry page after a rebuild


def test_browser_crash_reports_reach_the_server_log_even_signed_out(client, caplog):
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    anonymous = TestClient(app)
    with caplog.at_level("ERROR", logger="guardlens.client"):
        r = anonymous.post("/api/client-log", json={"message": "boom", "stack": "at x", "page": "/app/", "agent": "test"})
    assert r.status_code == 204 and "BROWSER ERROR on /app/" in caplog.text and "boom" in caplog.text


def test_browser_crash_reports_cannot_forge_log_lines(client, caplog):
    with caplog.at_level("ERROR", logger="guardlens.client"):
        client.post("/api/client-log", json={"message": "a\n2026-01-01 ERROR fake: login ok", "stack": "x\ny", "page": "/p\nq", "agent": "u\na"})
    assert len(caplog.records) == 1 and "\n" not in caplog.records[0].getMessage()


def test_nothing_comes_through_a_tunnel_until_an_admin_exists(client):
    for header in ({"X-Forwarded-For": "203.0.113.9"}, {"CF-Connecting-IP": "203.0.113.9"}, {"Tailscale-User-Login": "x@y"}):
        for path, method in (("/api/cameras", "get"), ("/api/auth/status", "get"), ("/app/", "get")):
            r = getattr(client, method)(path, headers=header)
            assert r.status_code == 403 and "not set up yet" in r.json()["detail"], (header, path)
        assert client.post("/api/auth/setup", headers=header, json={"username": "thief", "password": PASSWORD}).status_code == 403
    assert client.get("/api/cameras").status_code == 200  # the same computer, no proxy: works as before
    client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD})
    # once an admin exists the normal login rules take over (a proxied, signed-out visitor sees the sign-in screen)
    assert client.get("/api/auth/status", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200
