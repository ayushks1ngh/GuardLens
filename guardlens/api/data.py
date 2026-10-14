"""Data safety API: backups, retention, storage use (sign-in protected like the rest of /api)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from guardlens import auth, maintenance
from guardlens.config import load_config

def _full_access(request: Request) -> None:
    """Backups hold password hashes, camera passwords and notifier secrets: a read-only token must not reach them."""
    problem = auth.full_access_or_open(request.headers, request.cookies)
    if problem:
        raise HTTPException(401 if problem == "login required" else 403, problem)


router = APIRouter(prefix="/api/data", tags=["data"], dependencies=[Depends(_full_access)])


def _named_backup(name: str):
    if not maintenance.BACKUP_NAME.fullmatch(name):  # also blocks path tricks like ../
        raise HTTPException(404, "No such backup.")
    path = maintenance.backups_dir(load_config()) / name
    if not path.is_file():
        raise HTTPException(404, "No such backup.")
    return path


@router.get("/status")
def status():
    cfg = load_config()
    from guardlens import migrations
    from guardlens.events import get_engine
    return {"backups": maintenance.list_backups(cfg), "storage": maintenance.storage_summary(cfg),
            "schema": {"version": migrations.get_version(get_engine()), "latest": migrations.latest_version()},
            "backup_policy": cfg.backup.model_dump(), "retention_policy": cfg.retention.model_dump()}


@router.post("/backups", status_code=201)
def make_backup():
    return maintenance.create_backup(load_config(), "manual")


@router.get("/backups/{name}")
def download_backup(name: str):
    path = _named_backup(name)
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.delete("/backups/{name}")
def delete_backup(name: str):
    _named_backup(name).unlink()
    return {"status": "deleted", "name": name}


@router.post("/cleanup")
def cleanup_now():
    cfg = load_config()
    return {"events_removed": maintenance.prune_events(cfg), "backups_removed": maintenance.prune_backups(cfg)}
