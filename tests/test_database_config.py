from pathlib import Path

import database.database as db


def test_relative_database_path_resolves_from_project_root():
    resolved = db._resolve_database_path("data/custom.db")
    assert resolved == db.BASE_DIR / "data" / "custom.db"


def test_absolute_database_path_is_preserved(tmp_path):
    configured = tmp_path / "custom.db"
    assert db._resolve_database_path(str(configured)) == configured


def test_database_connection_creates_parent_directories(tmp_path, monkeypatch):
    database_file = tmp_path / "nested" / "folder" / "custom.db"
    monkeypatch.setattr(db, "DATABASE_PATH", database_file)

    connection = db.get_db_connection()
    try:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        connection.close()

    assert database_file.exists()
