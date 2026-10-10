"""Runtime cache for persisted zones/rules; refreshed only on CRUD changes."""
from __future__ import annotations

import threading

from sqlmodel import Session, select

from guardlens.events import Rule as RuleModel
from guardlens.events import Zone as ZoneModel
from guardlens.events import get_engine
from guardlens.rules import RuleConfig
from guardlens.types import Zone


class PolicyStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._zones: dict[int, list[Zone]] = {}
        self._rules: list[RuleConfig] = []

    def reload(self) -> None:
        with Session(get_engine()) as session:
            zone_rows = session.exec(select(ZoneModel)).all()
            rule_rows = session.exec(select(RuleModel).where(RuleModel.enabled == True)).all()  # noqa: E712
        zones: dict[int, list[Zone]] = {}
        for row in zone_rows:
            zones.setdefault(row.camera_id, []).append(
                Zone(id=row.id, name=row.name, polygon=[tuple(p) for p in row.polygon])
            )
        rules = [
            RuleConfig(
                type=r.type,
                name=r.name,
                camera_id=r.camera_id,
                zone_id=r.zone_id,
                severity=r.severity,
                cooldown_seconds=r.cooldown_seconds,
                params=r.params,
            )
            for r in rule_rows
        ]
        with self._lock:
            self._zones = zones
            self._rules = rules

    def zones_for(self, camera_id: int) -> list[Zone]:
        with self._lock:
            return list(self._zones.get(camera_id, []))

    def rules(self) -> list[RuleConfig]:
        with self._lock:
            return list(self._rules)


policy_store = PolicyStore()
