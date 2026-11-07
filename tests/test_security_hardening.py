from datetime import date
from unittest.mock import patch

import database.database as db
import app as app_module
from tests.conftest import login


def test_csrf_token_required_for_chat(client, test_app, user_id, monkeypatch):
    monkeypatch.setitem(test_app.config, "CSRF_ENABLED", True)
    login(client, user_id)

    response = client.post("/api/chat", json={"message": "Hello"})

    assert response.status_code == 400
    assert db.get_conversations_for_user(user_id) == []


def test_csrf_token_from_chat_page_allows_chat(client, test_app, user_id, monkeypatch):
    monkeypatch.setitem(test_app.config, "CSRF_ENABLED", True)
    login(client, user_id)
    client.get("/chat")
    with client.session_transaction() as session:
        token = session["_csrf_token"]

    with patch.object(app_module, "get_ai_response", return_value=(True, "Hello")):
        response = client.post(
            "/api/chat",
            json={"message": "Hello"},
            headers={"X-CSRF-Token": token},
        )

    assert response.status_code == 200


def test_chat_rejects_oversized_message_without_persisting(client, user_id):
    login(client, user_id)

    response = client.post("/api/chat", json={"message": "x" * (app_module.MAX_CHAT_MESSAGE_LENGTH + 1)})

    assert response.status_code == 413
    assert db.get_conversations_for_user(user_id) == []


def test_daily_request_limit_blocks_writes(client, user_id):
    login(client, user_id)
    connection = db.get_db_connection()
    connection.execute(
        "INSERT INTO usage (user_id, date, message_count, request_count) VALUES (?, ?, 0, ?)",
        (user_id, date.today().isoformat(), db.DAILY_CHAT_REQUEST_LIMIT),
    )
    connection.commit()
    connection.close()

    with patch.object(app_module, "get_ai_response") as ai:
        response = client.post("/api/chat", json={"message": "Please help"})

    assert response.status_code == 429
    assert response.json["request_limit_reached"] is True
    ai.assert_not_called()
    assert db.get_conversations_for_user(user_id) == []


def test_ai_quota_limit_blocks_message_persistence(client, user_id):
    login(client, user_id)
    for _ in range(db.DAILY_MESSAGE_LIMIT):
        db.increment_usage(user_id)

    response = client.post("/api/chat", json={"message": "Please help"})

    assert response.status_code == 429
    assert db.get_conversations_for_user(user_id) == []


def test_session_cookie_security_defaults(test_app):
    assert test_app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert test_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert test_app.config["SESSION_COOKIE_SECURE"] is app_module.IS_PRODUCTION


def test_logout_is_post_only_and_csrf_protected(client, test_app, user_id, monkeypatch):
    monkeypatch.setitem(test_app.config, "CSRF_ENABLED", True)
    login(client, user_id)

    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400

    client.get("/chat")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    response = client.post("/logout", data={"csrf_token": token})

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "user_id" not in session