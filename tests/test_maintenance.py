"""Stage 1: backups restore real data; retention removes only what it should."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from guardlens import maintenance
from guardlens.app import app
from guardlens.config import load_config
from guardlens.events import Camera, Event, EventNote, get_engine
from guardlens.events.store import event_store
from guardlens.types import EventDraft


def _camera() -> int:
    with Session(get_engine()) as session:
        camera = Camera(name="Retention cam", source="none", enabled=False)
        session.add(camera); session.commit(); session.refresh(camera)
        return camera.id


def _event(camera_id, severity, days_old, resolved=False, picture=True):
    draft = EventDraft(type="person", severity=severity,
                       snapshot=np.full((20, 30, 3), 120, dtype=np.uint8) if picture else None)
    when = datetime.now(timezone.utc) - timedelta(days=days_old)
    event = event_store.persist(camera_id, draft, created_at=when)
    if resolved:
        with Session(get_engine()) as session:
            row = session.get(Event, event.id); row.status = "resolved"; session.add(row); session.commit()
    return event.id


def test_backup_is_a_real_restorable_copy_and_listing_ignores_foreign_files():
    cfg = load_config()
    with TestClient(app):
        camera_id = _camera()
        entry = maintenance.create_backup(cfg, "manual")
        copy = maintenance.backups_dir(cfg) / entry["name"]
        rows = sqlite3.connect(str(copy)).execute("select name from camera where id=?", (camera_id,)).fetchall()
        assert rows == [("Retention cam",)]
        (maintenance.backups_dir(cfg) / "guardlens-before-something.db").write_bytes(b"x")  # a hand-made file
        names = [b["name"] for b in maintenance.list_backups(cfg)]
        assert entry["name"] in names and "guardlens-before-something.db" not in names


def test_backup_pruning_keeps_the_newest_and_never_touches_foreign_files():
    cfg = load_config()
    folder = maintenance.backups_dir(cfg)
    for old in folder.glob("guardlens-*-*.db"):
        old.unlink()
    foreign = folder / "guardlens-before-camera-dedup-20261010-191921.db"
    foreign.write_bytes(b"keep me")
    names = []
    for i in range(6):  # 6 auto backups, aged 20..15 days
        path = folder / f"guardlens-auto-2026010{i + 1}-030000.db"
        path.write_bytes(b"db")
        t = time.time() - (20 - i) * 86400
        os.utime(path, (t, t)); names.append(path.name)
    assert maintenance.prune_backups(cfg) == 3  # keep_days=14 -> all are old, but the newest 3 stay
    left = {b["name"] for b in maintenance.list_backups(cfg)}
    assert left == set(names[-3:]) and foreign.exists()


def test_retention_removes_old_events_with_pictures_but_keeps_what_matters():
    cfg = load_config()
    with TestClient(app):
        cam = _camera()
        old_info = _event(cam, "info", 200)
        old_critical_open = _event(cam, "critical", 200)                  # nobody dealt with it: keep
        old_critical_done = _event(cam, "critical", 200, resolved=True)   # handled: may go
        recent = _event(cam, "warning", 5)
        with Session(get_engine()) as session:
            session.add(EventNote(event_id=old_info, text="note")); session.commit()
            snapshot = session.get(Event, old_info).snapshot_path
        assert (event_store._snapshots_dir / snapshot).exists()

        removed = maintenance.prune_events(cfg)

        with Session(get_engine()) as session:
            alive = {e.id for e in session.exec(select(Event)).all()}
            assert old_info not in alive and old_critical_done not in alive
            assert old_critical_open in alive and recent in alive
            assert session.exec(select(EventNote).where(EventNote.event_id == old_info)).all() == []
        assert removed == 2 and not (event_store._snapshots_dir / snapshot).exists()


def test_retention_can_be_switched_off():
    cfg = load_config().model_copy(deep=True)
    cfg.retention.enabled = False
    with TestClient(app):
        old = _event(_camera(), "info", 400, picture=False)
        assert maintenance.prune_events(cfg) == 0
        with Session(get_engine()) as session:
            assert session.get(Event, old) is not None


def test_data_api_backup_download_delete_and_path_safety():
    with TestClient(app) as client:
        made = client.post("/api/data/backups")
        assert made.status_code == 201
        name = made.json()["name"]
        status = client.get("/api/data/status").json()
        assert name in [b["name"] for b in status["backups"]]
        assert status["retention_policy"]["events_days"] == 90 and status["storage"]["database_mb"] >= 0
        assert client.get(f"/api/data/backups/{name}").content[:15] == b"SQLite format 3"
        assert client.get("/api/data/backups/..%2F..%2Fetc%2Fpasswd").status_code == 404
        assert client.delete("/api/data/backups/notes.txt").status_code == 404
        assert client.delete(f"/api/data/backups/{name}").json()["status"] == "deleted"
        assert client.post("/api/data/cleanup").json().keys() >= {"events_removed", "backups_removed"}


def test_health_asks_for_a_backup_when_there_is_none_and_stops_once_there_is():
    from guardlens.healthcheck import collect_issues
    cfg = load_config()
    with TestClient(app) as client:
        for old in maintenance.backups_dir(cfg).glob("guardlens-*-*.db"):
            old.unlink()
        assert any(i["area"] == "backup" for i in collect_issues(Path(cfg.data_dir)))
        client.post("/api/data/backups")
        assert not any(i["area"] == "backup" for i in collect_issues(Path(cfg.data_dir)))
