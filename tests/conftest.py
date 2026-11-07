import pytest

import database.database as db
import app as app_module


@pytest.fixture()
def test_app(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DATABASE_PATH", database_path)
    db.init_db()

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret", CSRF_ENABLED=False)
    with app_module.app.app_context():
        yield app_module.app


@pytest.fixture()
def client(test_app):
    return test_app.test_client()


@pytest.fixture()
def user_id():
    return db.get_or_create_guest_user()


def login(client, user_id, is_admin=False, user_name="Test User"):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_name"] = user_name
        session["is_admin"] = is_admin
