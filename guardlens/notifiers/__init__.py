"""Notifier plugins, automatic discovery, and failure-isolated dispatch."""
from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from guardlens.schema import normalize_schema

logger = logging.getLogger("guardlens.notifiers")


class Notifier:
    key = ""
    config_schema: dict = {}

    def setup(self, config: dict) -> None: self.config = config
    def send(self, event: dict) -> None: raise NotImplementedError


_REGISTRY: dict[str, type[Notifier]] = {}


def register_notifier(cls: type[Notifier]) -> type[Notifier]:
    if not cls.key: raise ValueError("notifier must define key")
    _REGISTRY[cls.key] = cls
    return cls


def get_notifier_class(key: str): return _REGISTRY.get(key)
def notifier_types():
    return [
        {
            "key": k,
            "label": getattr(c, "label", "") or k.replace("_", " ").capitalize(),
            "config_schema": c.config_schema,
            "fields": normalize_schema(c.config_schema),
        }
        for k, c in sorted(_REGISTRY.items())
    ]


class NotifierDispatcher:
    def __init__(self):
        self._entries = []
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="notify")

    def reload(self):
        from sqlmodel import Session, select
        from guardlens.events import NotifierConfig, get_engine
        with Session(get_engine()) as session:
            rows = session.exec(select(NotifierConfig).where(NotifierConfig.enabled == True)).all()  # noqa: E712
        entries = []
        for row in rows:
            cls = get_notifier_class(row.type)
            if not cls:
                logger.warning("unknown notifier type %s", row.type); continue
            try:
                instance = cls()
                instance.setup(row.config)
                entries.append((row.id, row.min_severity, instance))
            except Exception:
                logger.exception("notifier %s configuration is invalid; skipping", row.id)
        with self._lock: self._entries = entries

    def dispatch(self, event: dict):
        levels = {"info": 0, "warning": 1, "critical": 2}
        with self._lock: entries = list(self._entries)
        futures = []
        for notifier_id, minimum, notifier in entries:
            if levels.get(event.get("severity", "warning"), 1) < levels.get(minimum, 1): continue
            futures.append(self._pool.submit(self._safe_send, notifier_id, notifier, event))
        return futures

    @staticmethod
    def _safe_send(notifier_id, notifier, event):
        try: notifier.send(event); return True
        except Exception:
            logger.exception("notifier %s failed; event pipeline unaffected", notifier_id)
            return False

    def shutdown(self): self._pool.shutdown(wait=True, cancel_futures=True)


def _discover():
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if not module.name.startswith("_") and module.name not in {"base"}:
            importlib.import_module(f"{__name__}.{module.name}")


_discover()
dispatcher = NotifierDispatcher()
