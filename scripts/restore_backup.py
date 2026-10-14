"""Restore the GuardLens database from a backup. STOP the server first.

Usage: python scripts/restore_backup.py                 # list backups
       python scripts/restore_backup.py <backup-name>   # restore one
The current database is saved next to it as guardlens-before-restore-<time>.db before anything is replaced.
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens.config import load_config  # noqa: E402
from guardlens import maintenance  # noqa: E402


def main() -> int:
    cfg = load_config()
    folder = maintenance.backups_dir(cfg)
    backups = maintenance.list_backups(cfg)
    if len(sys.argv) < 2:
        print(f"Backups in {folder}:")
        for b in backups:
            print(f"  {b['name']}  {b['size_mb']} MB  {b['created_at']}")
        print("Restore one with: python scripts/restore_backup.py <name>")
        return 0
    name = sys.argv[1]
    if not maintenance.BACKUP_NAME.match(name) or not (folder / name).is_file():
        print(f"No such backup: {name}")
        return 1
    check = sqlite3.connect(str(folder / name)).execute("pragma integrity_check").fetchone()[0]
    if check != "ok":
        print(f"Backup failed its integrity check ({check}); not restoring.")
        return 1
    live = maintenance._db_file(cfg)
    if live.exists():
        saved = folder / f"guardlens-before-restore-{datetime.now():%Y%m%d-%H%M%S}.db"
        shutil.copy2(live, saved)
        print(f"Current database saved as {saved.name}")
    for suffix in ("-wal", "-shm"):
        Path(str(live) + suffix).unlink(missing_ok=True)
    shutil.copy2(folder / name, live)
    print(f"Restored {name}. Start GuardLens again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
