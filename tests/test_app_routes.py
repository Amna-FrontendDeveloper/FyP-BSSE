from unittest.mock import patch

import database.database as db
import app as app_module
from tests.conftest import login


def test_anonymous_pages_redirect(client):
    assert client.get("/").status_code == 302
    assert client.get("/admin").status_code == 302


def test_non_admin_cannot_access_admin(client, user_id):
    login(client, user_id)
    response = client.get("/admin")
    assert response.status_code == 403
    assert db.get_logs(log_type="security")


def test_admin_pages_render(client, user_id):
    db.ensure_admin_by_email("admin@example.com")
    connection = db.get_db_connection()
    connection.execute("UPDATE users SET email = ?, is_admin = 1 WHERE id = ?", ("admin@example.com", user_id))
    connection.commit()
    connection.close()
    login(client, user_id, is_admin=True, user_name="Admin")

    assert client.get("/admin").status_code == 200
    assert client.get("/admin/users").status_code == 200
    assert client.get("/admin/logs").status_code == 200


def test_admin_cannot_disable_self(client, user_id):
    connection = db.get_db_connection()
    connection.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
    connection.commit()
    connection.close()
    login(client, user_id, is_admin=True)
    response = client.post(f"/admin/users/{user_id}/toggle-disabled")
    assert response.status_code == 302
    assert db.is_user_disabled(user_id) is False


def test_admin_can_disable_and_enable_other_user(client, user_id):
    other_id = db.get_or_create_guest_user()
    connection = db.get_db_connection()
    connection.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
    connection.commit()
    connection.close()
    login(client, user_id, is_admin=True, user_name="Admin")

    response = client.post(f"/admin/users/{other_id}/toggle-disabled")
    assert response.status_code == 302
    assert db.is_user_disabled(other_id) is True
    assert db.get_logs(log_type="activity")[0]["message"]

    client.post(f"/admin/users/{other_id}/toggle-disabled")
    assert db.is_user_disabled(other_id) is False


def test_chat_rejects_empty_message(client, user_id):
    login(client, user_id)
    response = client.post("/api/chat", json={"message": "  "})
    assert response.status_code == 400
    assert response.json["error"] == "Message cannot be empty."


def test_pre_ai_escalation_skips_ai_and_quota(client, user_id):
    login(client, user_id)
    with patch.object(app_module, "get_ai_response") as ai:
        response = client.post("/api/chat", json={"message": "I want a refund"})
    assert response.status_code == 200
    assert response.json["escalated"] is True
    ai.assert_not_called()
    assert db.get_today_message_count(user_id) == 0
    assert db.get_unresolved_escalation_count(user_id) == 1


def test_successful_chat_increments_usage(client, user_id):
    login(client, user_id)
    with patch.object(app_module, "get_ai_response", return_value=(True, "Here is the answer.")):
        response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json["reply"] == "Here is the answer."
    assert response.json["messages_used_today"] == 1


def test_post_ai_escalation_marks_conversation(client, user_id):
    login(client, user_id)
    with patch.object(app_module, "get_ai_response", return_value=(True, "I couldn't find that information.")):
        response = client.post("/api/chat", json={"message": "Where is my order?"})
    assert response.status_code == 200
    assert response.json["escalated"] is True
    assert db.get_unresolved_escalation_count(user_id) == 1


def test_ai_failure_logs_and_returns_502(client, user_id):
    login(client, user_id)
    with patch.object(app_module, "get_ai_response", return_value=(False, "Service unavailable")):
        response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 502
    assert response.json["error"] == "Service unavailable"
    assert db.get_logs(log_type="error")[0]["message"] == "AI service failure: Service unavailable"
    assert db.get_today_message_count(user_id) == 0


def test_daily_limit_blocks_ai(client, user_id):
    login(client, user_id)
    for _ in range(db.DAILY_MESSAGE_LIMIT):
        db.increment_usage(user_id)
    with patch.object(app_module, "get_ai_response") as ai:
        response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 429
    ai.assert_not_called()


def test_disabled_user_is_rejected(client, user_id):
    db.set_user_disabled(user_id, True)
    login(client, user_id)
    assert client.get("/chat").status_code == 302
    login(client, user_id)
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 403


def test_escalation_can_be_resolved(client, user_id):
    login(client, user_id)
    conversation_id = db.get_or_create_conversation(user_id)
    db.mark_conversation_escalated(conversation_id, "test")
    response = client.post(f"/conversations/{conversation_id}/resolve")
    assert response.status_code == 302
    assert db.get_unresolved_escalation_count(user_id) == 0
