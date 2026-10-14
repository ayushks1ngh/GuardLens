"""Stage 1.3: databases from older versions upgrade safely; failures roll back; nothing runs twice."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from guardlens import migrations
from guardlens.events.models import init_engine


def _url(tmp_path: Path, name="t.db") -> str:
    return f"sqlite:///{tmp_path / name}"


def _backups(tmp_path: Path):
    return list((tmp_path / "backups").glob("guardlens-before-migration-*.db"))


def test_fresh_database_is_stamped_latest_without_a_backup(tmp_path):
    engine = init_engine(_url(tmp_path))
    assert migrations.get_version(engine) == migrations.latest_version()
    assert _backups(tmp_path) == []


def _make_legacy_db(path: Path) -> None:
    """A database from before typed camera sources and before schema versions existed."""
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE camera (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, source VARCHAR NOT NULL, "
              "enabled BOOLEAN NOT NULL, analyze_fps FLOAT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
    c.execute("INSERT INTO camera VALUES (7, 'Old door', 'rtsp://cam/1', 1, NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00')")
    c.commit(); c.close()


def test_legacy_database_upgrades_keeping_data_and_is_backed_up_first(tmp_path):
    _make_legacy_db(tmp_path / "t.db")
    engine = init_engine(_url(tmp_path))
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, source, source_type, source_config FROM camera WHERE id = 7")).one()
    assert tuple(row)[:3] == ("Old door", "rtsp://cam/1", "opencv") and str(row[3]) == "{}"
    assert migrations.get_version(engine) == migrations.latest_version()
    [backup] = _backups(tmp_path)
    old = sqlite3.connect(str(backup)).execute("SELECT name FROM camera").fetchall()
    assert old == [("Old door",)]  # the backup is the database as it was before the upgrade
    cols = {r[1] for r in sqlite3.connect(str(backup)).execute("PRAGMA table_info(camera)")}
    assert "source_type" not in cols


def test_second_start_does_nothing(tmp_path):
    _make_legacy_db(tmp_path / "t.db")
    init_engine(_url(tmp_path))
    init_engine(_url(tmp_path))
    assert len(_backups(tmp_path)) == 1


def test_missing_nullable_column_is_repaired(tmp_path):
    engine = init_engine(_url(tmp_path))
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE event DROP COLUMN clip_path"))
    assert "event.clip_path: added" in migrations.repair_missing_columns(engine)
    with engine.connect() as conn:
        assert "clip_path" in {c[1] for c in conn.execute(text("PRAGMA table_info(event)"))}
    assert migrations.repair_missing_columns(engine) == []  # nothing left to fix


def test_failed_migration_rolls_back_and_stops(tmp_path):
    engine = init_engine(_url(tmp_path))
    with engine.begin() as conn:
        conn.execute(text("UPDATE schema_info SET version = 0"))
        conn.execute(text("CREATE TABLE scratch (n INTEGER)"))

    def ok(conn): conn.execute(text("INSERT INTO scratch VALUES (1)"))
    def boom(conn):
        conn.execute(text("INSERT INTO scratch VALUES (2)"))
        raise RuntimeError("nope")
    def never(conn): conn.execute(text("INSERT INTO scratch VALUES (3)"))

    steps = [migrations.Migration(1, "ok", ok), migrations.Migration(2, "boom", boom), migrations.Migration(3, "never", never)]
    with pytest.raises(RuntimeError):
        migrations.migrate(engine, fresh=False, migrations=steps)
    with engine.connect() as conn:
        assert [r[0] for r in conn.execute(text("SELECT n FROM scratch"))] == [1]  # step 2 rolled back, step 3 never ran
    assert migrations.get_version(engine) == 1
    assert len(_backups(tmp_path)) == 1  # backed up before trying


def test_not_null_column_without_default_is_reported_not_guessed(tmp_path):
    from sqlmodel import SQLModel
    engine = init_engine(_url(tmp_path))
    column = SQLModel.metadata.tables["person"].columns["name"]
    assert column.nullable is False and column.default is None  # the premise of this test
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE person"))
        conn.execute(text("CREATE TABLE person (id INTEGER PRIMARY KEY)"))
    report = migrations.repair_missing_columns(engine)
    assert any(r.startswith("person.name:") and "needs a numbered migration" in r for r in report)
    with engine.connect() as conn:
        assert "name" not in {c[1] for c in conn.execute(text("PRAGMA table_info(person)"))}  # never guessed a value
