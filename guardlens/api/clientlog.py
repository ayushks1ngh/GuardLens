"""Browser crash reports: the dashboard posts uncaught errors here so they land in the server log."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/client-log", tags=["diagnostics"])
logger = logging.getLogger("guardlens.client")
_recent: list[float] = []  # timestamps; caps log spam from a crash loop


class ClientError(BaseModel):
    message: str = Field(max_length=500)
    stack: str = Field(default="", max_length=2000)
    page: str = Field(default="", max_length=200)
    agent: str = Field(default="", max_length=200)


@router.post("", status_code=204, response_class=Response)
def report(body: ClientError):
    now = time.time()
    _recent[:] = [t for t in _recent if now - t < 60]
    if len(_recent) >= 10:
        return Response(status_code=204)
    _recent.append(now)
    clean = lambda text: " ".join(text.split())  # one log line per report; no forged lines
    logger.error("BROWSER ERROR on %s [%s]: %s | %s", clean(body.page), clean(body.agent), clean(body.message), clean(body.stack))
    return Response(status_code=204)
