"""Create a consistent backup of the SQLite database."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


source = Path(os.getenv("DATABASE_PATH", "database/app.db")).expanduser()
backup_dir = Path(os.getenv("BACKUP_DIR", "backups")).expanduser()
backup_dir.mkdir(parents=True, exist_ok=True)

if not source.exists():
    raise SystemExit(f"Database does not exist: {source}")

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
target = backup_dir / f"app-{stamp}.db"

with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
    source_connection.backup(target_connection)

print(f"Created database backup: {target}")
