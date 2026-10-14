"""Data safety: database backups and event retention (see docs/16-future-plan.md, Stage 1)."""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from guardlens.config import Config
from guardlens.events import Event, EventEmbedding, EventNote, get_engine
from guardlens.events.store import event_store

logger = logging.getLogger("guardlens.maintenance")

BACKUP_NAME = re.compile(r"^guardlens-(auto|manual)-\d{8}-\d{6}\.db$")
MIN_KEPT_BACKUPS = 3


def backups_dir(cfg: Config) -> Path:
    path = Path(cfg.data_dir) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db_file(cfg: Config) -> Path:
    url = cfg.resolved_db_url()
    if not url.startswith("sqlite:///"):
        raise RuntimeError("backups support the built-in SQLite database only")
    return Path(url.removeprefix("sqlite:///"))


def describe(path: Path) -> dict:
    stat = path.stat()
    return {"name": path.name, "kind": "auto" if "-auto-" in path.name else "manual",
            "size_mb": round(stat.st_size / 1_048_576, 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def list_backups(cfg: Config) -> list[dict]:
    files = [p for p in backups_dir(cfg).iterdir() if BACKUP_NAME.match(p.name)]
    return [describe(p) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def create_backup(cfg: Config, kind: str = "manual") -> dict:
    """Consistent copy of the live database (SQLite online-backup API: safe while the app is running)."""
    target = backups_dir(cfg) / f"guardlens-{kind}-{datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(str(_db_file(cfg)))
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    logger.info("Database backup written: %s", target.name)
    return describe(target)


def prune_backups(cfg: Config, now: Optional[datetime] = None) -> int:
    """Delete our own backups older than keep_days, always keeping the newest few. Other files are never touched."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cfg.backup.keep_days)
    entries = list_backups(cfg)  # newest first
    removed = 0
    for entry in entries[MIN_KEPT_BACKUPS:]:
        if datetime.fromisoformat(entry["created_at"]) < cutoff:
            (backups_dir(cfg) / entry["name"]).unlink(missing_ok=True)
            removed += 1
    return removed


def nightly_backup(cfg: Config) -> None:
    if cfg.backup.enabled:
        create_backup(cfg, "auto")
        prune_backups(cfg)


def prune_events(cfg: Config, now: Optional[datetime] = None, batch: int = 200) -> int:
    """Remove events older than retention.events_days with their notes, search vectors, pictures and clips.

    Unresolved critical alerts are always kept: someone has not dealt with them yet.
    """
    if not cfg.retention.enabled:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=cfg.retention.events_days)).replace(tzinfo=None)
    removed = 0
    while True:
        with Session(get_engine()) as session:
            old = session.exec(
                select(Event).where(Event.created_at < cutoff)
                .where((Event.severity != "critical") | (Event.status == "resolved"))
                .order_by(Event.created_at).limit(batch)
            ).all()
            if not old:
                break
            for event in old:
                for row in session.exec(select(EventNote).where(EventNote.event_id == event.id)).all():
                    session.delete(row)
                for row in session.exec(select(EventEmbedding).where(EventEmbedding.event_id == event.id)).all():
                    session.delete(row)
                event_store.delete_evidence(event)
                session.delete(event)
            session.commit()
            removed += len(old)
    if removed:
        logger.info("Retention removed %s events older than %s days", removed, cfg.retention.events_days)
    return removed


def storage_summary(cfg: Config) -> dict:
    def size(path: Path) -> float:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0
        return round(total / 1_048_576, 1)

    db = _db_file(cfg)
    return {"database_mb": round(db.stat().st_size / 1_048_576, 1) if db.exists() else 0.0,
            "pictures_mb": size(cfg.snapshots_dir()), "clips_mb": size(Path(cfg.data_dir) / "clips"),
            "backups_mb": size(backups_dir(cfg))}
