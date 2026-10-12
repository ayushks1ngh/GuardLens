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


ROUTING_SCHEMA = {
    "quiet_enabled": {"type": "boolean", "default": False, "label": "Quiet hours",
                      "help": "During quiet hours only serious alerts are sent out; everything is still recorded."},
    "quiet_start": {"type": "HH:MM", "default": "23:00", "label": "Quiet hours start"},
    "quiet_end": {"type": "HH:MM", "default": "07:00", "label": "Quiet hours end"},
    "quiet_min_severity": {"type": "enum", "default": "critical", "label": "Still send alerts that are",
                           "enum": [{"value": "warning", "label": "Warning or higher"},
                                    {"value": "critical", "label": "Critical only"}]},
}


def in_quiet_hours(routing: dict, now_hhmm: str) -> bool:
    if not routing.get("quiet_enabled"):
        return False
    start, end = routing.get("quiet_start", "23:00"), routing.get("quiet_end", "07:00")
    return (now_hhmm >= start or now_hhmm < end) if start > end else (start <= now_hhmm < end)


class NotifierDispatcher:
    def __init__(self):
        self._entries = []
        self._routing: dict = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="notify")

    def reload(self):
        from sqlmodel import Session, select
        from guardlens.events import NotifierConfig, Setting, get_engine
        with Session(get_engine()) as session:
            rows = session.exec(select(NotifierConfig).where(NotifierConfig.enabled == True)).all()  # noqa: E712
            routing_row = session.get(Setting, "notification_routing")
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
        with self._lock:
            self._entries = entries
            self._routing = dict((routing_row.value or {}) if routing_row else {})

    def routing(self) -> dict:
        defaults = {k: v["default"] for k, v in ROUTING_SCHEMA.items()}
        return {**defaults, **self._routing}

    def dispatch(self, event: dict):
        from datetime import datetime
        levels = {"info": 0, "warning": 1, "critical": 2}
        with self._lock: entries = list(self._entries)
        if in_quiet_hours(self.routing(), datetime.now().strftime("%H:%M")) and \
                levels.get(event.get("severity", "warning"), 1) < levels.get(self.routing()["quiet_min_severity"], 2):
            logger.info("quiet hours: not sending %s alert", event.get("type"))
            return []
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
