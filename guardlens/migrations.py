"""Versioned schema upgrades for the built-in SQLite database (docs/16-future-plan.md, Stage 1.3).

``SQLModel.metadata.create_all`` only creates missing *tables*; it never changes an existing one. This module covers
the rest, in two layers:

* **Column repair** (automatic): a column the models have but the database lacks is added when that is safe
  (nullable, or with a plain default).
* **Numbered migrations**: for anything repair cannot do (data changes, NOT NULL without default, renames). Each runs
  once, in a transaction, after an automatic backup; a failure rolls the step back and stops the upgrade.

To change the schema: edit the model, and if repair is not enough append a ``Migration`` with the next number.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger("guardlens.migrations")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    run: Callable[[Connection], None]


def _camera_source_columns(connection: Connection) -> None:
    """Phase A: typed camera sources. Old rows keep their source string; the adapter interprets it."""
    columns = {c["name"] for c in inspect(connection).get_columns("camera")}
    if "source_type" not in columns:
        connection.execute(text("ALTER TABLE camera ADD COLUMN source_type VARCHAR NOT NULL DEFAULT 'opencv'"))
    if "source_config" not in columns:
        connection.execute(text("ALTER TABLE camera ADD COLUMN source_config JSON NOT NULL DEFAULT '{}'"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_camera_source_type ON camera (source_type)"))


MIGRATIONS: list[Migration] = [
    Migration(1, "typed camera sources", _camera_source_columns),
]


def latest_version(migrations: Optional[list[Migration]] = None) -> int:
    return max((m.version for m in (MIGRATIONS if migrations is None else migrations)), default=0)


def _ensure_version_table(connection: Connection) -> None:
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_info (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)"))


def get_version(engine: Engine) -> int:
    with engine.begin() as connection:
        _ensure_version_table(connection)
        row = connection.execute(text("SELECT version FROM schema_info WHERE id = 1")).first()
    return int(row[0]) if row else 0


def _set_version(connection: Connection, version: int) -> None:
    connection.execute(text("INSERT INTO schema_info (id, version) VALUES (1, :v) "
                            "ON CONFLICT(id) DO UPDATE SET version = :v"), {"v": version})


def repair_missing_columns(engine: Engine) -> list[str]:
    """Add columns the models define but the database lacks. Returns what was added (or could not be)."""
    from sqlmodel import SQLModel

    report = []
    existing = set(inspect(engine).get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing:
            continue
        have = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            default = column.default.arg if column.default is not None and getattr(column.default, "is_scalar", False) else None
            if not column.nullable and default is None:
                report.append(f"{table.name}.{column.name}: NOT NULL without a default; needs a numbered migration")
                logger.error("Cannot auto-add %s.%s (NOT NULL, no default): write a migration", table.name, column.name)
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect=engine.dialect)}'
            if default is not None:
                literal = f"'{default}'" if isinstance(default, str) else int(default) if isinstance(default, bool) else default
                ddl += f" DEFAULT {literal}"
                if not column.nullable:
                    ddl += " NOT NULL"
            with engine.begin() as connection:
                connection.execute(text(ddl))
            report.append(f"{table.name}.{column.name}: added")
            logger.warning("Schema repair: added column %s.%s", table.name, column.name)
    return report


def _backup_before_upgrade(engine: Engine, from_version: int, to_version: int) -> Optional[Path]:
    path = engine.url.database
    if not path or not Path(path).exists():
        return None
    folder = Path(path).parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"guardlens-before-migration-v{from_version}-to-v{to_version}-{datetime.now():%Y%m%d-%H%M%S}.db"
    source, dest = sqlite3.connect(path), sqlite3.connect(str(target))
    try:
        source.backup(dest)
    finally:
        dest.close(); source.close()
    logger.warning("Database backed up before upgrade: %s", target.name)
    return target


def migrate(engine: Engine, *, fresh: bool, migrations: Optional[list[Migration]] = None) -> dict:
    """Bring the database to the latest version. ``fresh`` = the file had no tables before ``create_all`` ran."""
    migrations = MIGRATIONS if migrations is None else migrations
    latest = latest_version(migrations)
    if not engine.url.drivername.startswith("sqlite"):
        return {"from": None, "to": None, "applied": [], "repaired": [], "backup": None}
    with engine.begin() as connection:
        _ensure_version_table(connection)
    if fresh:
        with engine.begin() as connection:
            _set_version(connection, latest)
        return {"from": latest, "to": latest, "applied": [], "repaired": [], "backup": None}

    current = get_version(engine)
    pending = sorted((m for m in migrations if m.version > current), key=lambda m: m.version)
    backup = _backup_before_upgrade(engine, current, latest) if pending else None
    applied = []
    for migration in pending:
        try:
            with engine.begin() as connection:  # one transaction per step
                migration.run(connection)
                _set_version(connection, migration.version)
        except Exception:
            logger.exception("Migration %s (%s) failed and was rolled back; stopping the upgrade", migration.version, migration.name)
            raise
        applied.append(f"{migration.version}: {migration.name}")
        logger.warning("Applied migration %s: %s", migration.version, migration.name)
    repaired = repair_missing_columns(engine)
    return {"from": current, "to": latest, "applied": applied, "repaired": repaired,
            "backup": backup.name if backup else None}
