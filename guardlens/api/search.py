"""Footage search API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from guardlens.assistant import parse_time_range
from guardlens.search import search_service
from guardlens.search.service import _TIME_WORDS

router = APIRouter(prefix="/api/search", tags=["search"])


class SettingsBody(BaseModel):
    enabled: bool


@router.get("/status")
def status():
    return search_service.status()


@router.put("/settings")
def settings(body: SettingsBody):
    search_service.update_settings({"enabled": body.enabled})
    if body.enabled:
        search_service.reindex_all()
    return search_service.status()


@router.post("/reindex")
def reindex():
    if not search_service.enabled:
        raise HTTPException(409, "Turn search on first.")
    search_service.reindex_all()
    return search_service.status()


@router.get("")
def search(
    q: str = Query(min_length=2, max_length=200),
    camera_id: Optional[int] = None,
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = None,
    limit: int = Query(24, ge=1, le=100),
):
    if not search_service.enabled:
        raise HTTPException(409, "Footage search is turned off.")
    start, end = from_, to
    if start is None and end is None and _TIME_WORDS.search(q):
        start, end, _ = parse_time_range(q)
    try:
        results = search_service.search(q, camera_id=camera_id, start=start, end=end, limit=limit)
    except Exception as exc:
        raise HTTPException(503, f"Search model unavailable: {exc}") from exc
    return {"query": q, "results": results}


@router.get("/similar/{event_id}")
def similar(event_id: int, limit: int = Query(12, ge=1, le=50)):
    return {"results": search_service.similar(event_id, limit)}
