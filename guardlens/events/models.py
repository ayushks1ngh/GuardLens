"""SQLModel database models and engine setup (see docs/03-data-model.md).

SQLite by default; Postgres-compatible by changing the connection URL only.
JSON columns (``params``, ``metadata``, ``summary``, ``config``) are the main
flexibility lever: new rule/detector/notifier types need no schema migration.
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, Index
from sqlalchemy import JSON as SA_JSON
from sqlmodel import Field, SQLModel, create_engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Camera(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # ``source`` remains as the backward-compatible display/open value. New
    # transports use source_type + JSON source_config (migration-safe seam).
    source: str
    source_type: str = Field(default="opencv", index=True)
    source_config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON))
    enabled: bool = True
    analyze_fps: Optional[float] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Zone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    camera_id: int = Field(foreign_key="camera.id", index=True)
    name: str
    polygon: list[Any] = Field(default_factory=list, sa_column=Column(SA_JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str = Field(index=True)
    name: str
    camera_id: Optional[int] = Field(default=None, foreign_key="camera.id", index=True)
    zone_id: Optional[int] = Field(default=None, foreign_key="zone.id")
    enabled: bool = True
    severity: str = "warning"
    cooldown_seconds: float = 30.0
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    __table_args__ = (
        Index("ix_event_camera_created", "camera_id", "created_at"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str = Field(index=True)
    severity: str = Field(default="warning", index=True)
    status: str = Field(default="new", index=True)  # new | acknowledged | resolved
    camera_id: int = Field(foreign_key="camera.id", index=True)
    rule_id: Optional[int] = Field(default=None, foreign_key="rule.id")
    person_id: Optional[int] = Field(default=None, foreign_key="person.id")
    snapshot_path: Optional[str] = None
    clip_path: Optional[str] = None
    event_metadata: dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", SA_JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class EventNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    text: str
    created_at: datetime = Field(default_factory=utcnow)


class Person(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    watchlist: bool = False
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class FaceImage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", index=True)
    image_path: str
    embedding: list[Any] = Field(default_factory=list, sa_column=Column(SA_JSON))
    created_at: datetime = Field(default_factory=utcnow)


class NotifierConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON))
    min_severity: str = "warning"
    created_at: datetime = Field(default_factory=utcnow)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=Column(SA_JSON))


class ActivityLog(SQLModel, table=True):
    __table_args__ = (
        Index("ix_activity_camera_ts", "camera_id", "timestamp"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    camera_id: int = Field(foreign_key="camera.id", index=True)
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON))


class AgentRun(SQLModel, table=True):
    """Audit log: every agent execution, whether it annotated, skipped, or failed."""
    __table_args__ = (Index("ix_agentrun_agent_started", "agent_key", "started_at"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_key: str = Field(index=True)
    trigger: str  # event | schedule | on_demand
    event_id: Optional[int] = Field(default=None, index=True)
    status: str  # ok | skipped | budget | unavailable | error
    started_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0
    detail: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON))


class Report(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_type = Field(index=True)
    generated_at: datetime = Field(default_factory=utcnow)
    generator: str = "structured"
    content: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SA_JSON))
    text: str = ""


_engine = None


def init_engine(db_url: str):
    global _engine
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    _engine = create_engine(db_url, connect_args=connect_args)
    SQLModel.metadata.create_all(_engine)
    _migrate_camera_sources(_engine)
    return _engine


def _migrate_camera_sources(engine) -> None:
    """Add Phase-A camera columns to existing databases without data loss.

    A full migration framework can replace this small additive migration when
    schema evolution grows. Existing source strings remain authoritative and
    are interpreted by the OpenCV adapter when source_config is empty.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "camera" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("camera")}
    with engine.begin() as connection:
        if "source_type" not in columns:
            connection.execute(text(
                "ALTER TABLE camera ADD COLUMN source_type VARCHAR NOT NULL DEFAULT 'opencv'"
            ))
        if "source_config" not in columns:
            # JSON is represented as TEXT on SQLite; '{}' preserves old rows.
            connection.execute(text(
                "ALTER TABLE camera ADD COLUMN source_config JSON NOT NULL DEFAULT '{}'"
            ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_camera_source_type ON camera (source_type)"
        ))


def get_engine():
    if _engine is None:
        raise RuntimeError("Engine not initialized. Call init_engine() first.")
    return _engine
