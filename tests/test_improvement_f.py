"""Improvement Phase F: upgrade, security, recovery, and bounded load gates."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from guardlens.app import app
from guardlens.capture.webrtc import PairingService
from guardlens.config import Config
from guardlens.events.models import init_engine
from guardlens.recording import ClipRecorder


def test_security_headers_and_signaling_bounds():
    with TestClient(app) as client:
        response=client.get("/api/auth/status")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "camera=(self)" in response.headers["permissions-policy"]
        huge=client.post("/api/pairing/offer",json={"stream_id":"valid_stream","token":"x"*40,"sdp":"x"*1_000_001,"type":"offer"})
        assert huge.status_code == 422


def test_pairing_capacity_and_expiry_pruning():
    service=PairingService(max_sessions=1)
    first,_=service.create("one")
    try:
        service.create("two")
        raise AssertionError("pairing capacity was not enforced")
    except ValueError as exc:
        assert "too many" in str(exc)
    first.expires_at=time.time()-1
    second,_=service.create("two")
    assert second.stream_id != first.stream_id


def test_tls_configuration_is_optional_and_explicit():
    cfg=Config(ssl_certfile="cert.pem",ssl_keyfile="key.pem")
    assert cfg.ssl_certfile == "cert.pem" and cfg.ssl_keyfile == "key.pem"
    assert Config().ssl_certfile == ""


def test_legacy_database_upgrade_preserves_rows(tmp_path):
    path=tmp_path/"legacy.db"
    db=sqlite3.connect(path)
    db.execute("CREATE TABLE camera (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, source VARCHAR NOT NULL, enabled BOOLEAN NOT NULL, analyze_fps FLOAT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
    db.execute("INSERT INTO camera VALUES (1,'Old','0',1,6,'2020-01-01','2020-01-01')");db.commit();db.close()
    engine=init_engine(f"sqlite:///{path}")
    columns={item["name"] for item in inspect(engine).get_columns("camera")}
    assert {"source_type","source_config"} <= columns
    check=sqlite3.connect(path); assert check.execute("SELECT name,source FROM camera WHERE id=1").fetchone()==("Old","0");check.close()


def test_abandoned_partial_clips_are_removed_on_recovery(tmp_path):
    partial=tmp_path/"cam-1.partial.avi";partial.write_bytes(b"incomplete")
    recorder=ClipRecorder();recorder.configure(tmp_path,{"enabled":False})
    assert not partial.exists()


def test_three_publisher_bounded_soak():
    result=subprocess.run([".venv/bin/python","scripts/soak_publishers.py","--seconds","1","--publishers","3"],capture_output=True,text=True,timeout=10,check=True)
    assert "PASS: 3 isolated publishers" in result.stdout


def test_hsts_only_for_the_configured_public_host(monkeypatch):
    monkeypatch.setenv("GUARDLENS_PUBLIC_URL", "https://cams.example.com")
    with TestClient(app, base_url="https://cams.example.com") as client:
        assert "strict-transport-security" in client.get("/api/auth/status").headers
    with TestClient(app, base_url="https://localhost") as client:
        assert "strict-transport-security" not in client.get("/api/auth/status").headers
