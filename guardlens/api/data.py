"""Data safety API: backups, retention, storage use (sign-in protected like the rest of /api)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from guardlens import maintenance
from guardlens.config import load_config

router = APIRouter(prefix="/api/data", tags=["data"])


def _named_backup(name: str):
    if not maintenance.BACKUP_NAME.match(name):  # also blocks path tricks like ../
        raise HTTPException(404, "No such backup.")
    path = maintenance.backups_dir(load_config()) / name
    if not path.is_file():
        raise HTTPException(404, "No such backup.")
    return path


@router.get("/status")
def status():
    cfg = load_config()
    return {"backups": maintenance.list_backups(cfg), "storage": maintenance.storage_summary(cfg),
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
