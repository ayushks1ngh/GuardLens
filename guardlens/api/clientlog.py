"""Browser crash reports: the dashboard posts uncaught errors here so they land in the server log."""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from guardlens import auth

router = APIRouter(prefix="/api/client-log", tags=["diagnostics"])
logger = logging.getLogger("guardlens.client")
_per_address: dict[str, deque] = defaultdict(deque)  # one address cannot use up another's reports
_recent: deque = deque()                               # and a global ceiling protects the log itself
PER_ADDRESS, GLOBAL, WINDOW, MAX_BODY = 10, 100, 60.0, 8192
_UNSAFE = re.compile(r"[^\x20-\x7e\u00a0-\uffff]")  # drops newlines, ESC and every other control character


def _clean(text: str) -> str:
    return _UNSAFE.sub("?", " ".join(text.split()))


class ClientError(BaseModel):
    message: str = Field(max_length=500)
    stack: str = Field(default="", max_length=2000)
    page: str = Field(default="", max_length=200)
    agent: str = Field(default="", max_length=200)


def _allow(address: str, now: float) -> bool:
    for q in (_recent, _per_address[address]):
        while q and now - q[0] > WINDOW:
            q.popleft()
    if len(_per_address) > 1000:  # addresses are caller-controlled in the worst case: forget idle ones
        for key in [k for k, q in _per_address.items() if not q]:
            _per_address.pop(key, None)
    if len(_recent) >= GLOBAL or len(_per_address[address]) >= PER_ADDRESS:
        return False
    _recent.append(now); _per_address[address].append(now)
    return True


@router.post("", status_code=204, response_class=Response)
def report(body: ClientError, request: Request):
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "report too large")
    if _allow(auth.client_key(request), time.time()):
        logger.error("BROWSER ERROR on %s [%s]: %s | %s", _clean(body.page), _clean(body.agent), _clean(body.message), _clean(body.stack))
    return Response(status_code=204)
