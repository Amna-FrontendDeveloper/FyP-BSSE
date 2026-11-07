
"""
Integration/API tests using Flask's test client. Relies on the fixtures in
conftest.py (client, logged_in_client, admin_client), which point the app at
an isolated temporary database — nothing here touches your real app.db, and
no real network calls to Google, Groq, or a WooCommerce store are made
(all external calls are mocked).

Covers FYP test plan items: 1 (Authentication), 3 (Unauthorized access),
4 (AI chat), 5 (Empty message), 6 (AI API failure), 7 (Database failure),
10 (100-message limit), 11 (Daily reset), 12/13 (WooCommerce), 15 (Product-
aware AI), 18 (Human handoff), 19 (Admin authorization).
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

import database.database as db


# ---------- 1 & 3: Authentication / Unauthorized access ----------

def test_home_redirects_to_login_when_not_authenticated(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_api_chat_returns_401_json_when_not_authenticated(client):
    response = client.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 401
    assert response.get_json()["error"]


def test_dashboard_accessible_once_logged_in(logged_in_client):
    response = logged_in_client.get("/")
    assert response.status_code == 200


# ---------- 5: Empty message ----------

def test_empty_message_rejected_with_400(logged_in_client):
    response = logged_in_client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
    assert "empty" in response.get_json()["error"].lower()


# ---------- 4 & 6: AI chat happy path / AI API failure ----------

def test_successful_ai_chat_saves_conversation(logged_in_client):
    with patch("app.get_ai_response", return_value=(True, "Hello! How can I help?")):
        response = logged_in_client.post("/api/chat", json={"message": "hi there"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["reply"] == "Hello! How can I help?"

    conversations = db.get_conversations_for_user(logged_in_client.test_user_id)
    assert len(conversations) == 1
    assert conversations[0]["message_count"] == 2  # user msg + assistant reply


def test_ai_failure_returns_502_but_saves_conversation(logged_in_client):
    with patch("app.get_ai_response", return_value=(False, "AI service unavailable")):
        response = logged_in_client.post("/api/chat", json={"message": "hi there"})

    assert response.status_code == 502
    assert "unavailable" in response.get_json()["error"].lower()

    conversations = db.get_conversations_for_user(logged_in_client.test_user_id)
    assert conversations[0]["message_count"] == 2  # both user msg and failure reply saved


# ---------- 7: Database failure (simulated) ----------

def test_database_failure_returns_safe_500_not_crash(logged_in_client):
    with patch("app.get_or_create_conversation", side_effect=Exception("simulated DB failure")):
        response = logged_in_client.post("/api/chat", json={"message": "hi there"})

    assert response.status_code == 500
    body = response.get_json()
    assert "went wrong" in body["error"].lower()
    # Confirms no raw exception/stack trace leaked to the client
    assert "Traceback" not in response.get_data(as_text=True)


# ---------- 10 & 11: 100-message limit / daily reset ----------

def test_101st_message_blocked_with_upgrade_info(logged_in_client):
    user_id = logged_in_client.test_user_id
    for _ in range(100):
        db.increment_usage(user_id)

    with patch("app.get_ai_response", return_value=(True, "should not be called")):
        response = logged_in_client.post("/api/chat", json={"message": "one more please"})

    assert response.status_code == 429
    data = response.get_json()
    assert data["limit_reached"] is True
    assert "plan_name" in data["premium_info"]


def test_daily_reset_allows_new_messages(logged_in_client):
    user_id = logged_in_client.test_user_id
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    connection = db.get_db_connection()
    connection.execute(
        "INSERT INTO usage (user_id, date, message_count) VALUES (?, ?, ?)",
        (user_id, yesterday, 100),
    )
    connection.commit()
    connection.close()

    with patch("app.get_ai_response", return_value=(True, "Welcome back!")):
        response = logged_in_client.post("/api/chat", json={"message": "hello again"})

    assert response.status_code == 200  # yesterday's 100 did not carry over


# ---------- 18: Human handoff ----------

def test_human_request_escalates_without_calling_ai(logged_in_client):
    with patch("app.get_ai_response") as mock_ai:
        response = logged_in_client.post(
            "/api/chat", json={"message": "I want to speak to a human"}
        )
        mock_ai.assert_not_called()  # AI must never be called for this case

    assert response.status_code == 200
    data = response.get_json()
    assert data["escalated"] is True

    escalations = db.get_escalated_conversations_for_user(logged_in_client.test_user_id)
    assert len(escalations) == 1
    assert "human" in escalations[0]["escalation_reason"].lower()


def test_escalated_message_does_not_count_against_daily_limit(logged_in_client):
    user_id = logged_in_client.test_user_id
    logged_in_client.post("/api/chat", json={"message": "I want a refund"})
    assert db.get_today_message_count(user_id) == 0


# ---------- 15: Product-aware AI ----------

def test_product_context_passed_to_ai_when_product_matches(logged_in_client):
    user_id = logged_in_client.test_user_id
    db.save_woocommerce_integration(user_id, "https://example-store.com", "enc-key", "enc-secret")
    db.update_connection_status(user_id, "ecommerce", "connected")
    db.save_products(user_id, [{
        "external_product_id": "1",
        "name": "Red Cotton Dress",
        "price": "29.99",
        "stock_status": "instock",
        "description": "A lovely dress",
        "sku": "RCD-001",
        "variations": None,
    }])

    with patch("app.get_ai_response", return_value=(True, "It costs $29.99")) as mock_ai:
        response = logged_in_client.post(
            "/api/chat", json={"message": "What is the price of the Red Cotton Dress?"}
        )

    assert response.status_code == 200
    call_args = mock_ai.call_args
    product_context = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("product_context")
    assert product_context is not None
    assert "Red Cotton Dress" in product_context
    assert "29.99" in product_context


# ---------- 12 & 13: WooCommerce connection / invalid credentials ----------

def test_woocommerce_rejects_non_https_url(logged_in_client):
    response = logged_in_client.post(
        "/integrations/woocommerce/connect",
        data={"store_url": "http://insecure-store.com", "consumer_key": "ck_x", "consumer_secret": "cs_x"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    integration = db.get_integration(logged_in_client.test_user_id, "ecommerce")
    assert integration is None  # rejected before saving


def test_woocommerce_invalid_credentials_marks_failed(logged_in_client):
    user_id = logged_in_client.test_user_id
    logged_in_client.post(
        "/integrations/woocommerce/connect",
        data={"store_url": "https://example-store.com", "consumer_key": "ck_wrong", "consumer_secret": "cs_wrong"},
    )

    with patch("app.test_connection", return_value=(False, "Invalid Consumer Key or Consumer Secret.")):
        logged_in_client.post("/integrations/woocommerce/test")

    integration = db.get_integration(user_id, "ecommerce")
    assert integration["connection_status"] == "failed"


def test_woocommerce_valid_credentials_marks_connected(logged_in_client):
    user_id = logged_in_client.test_user_id
    logged_in_client.post(
        "/integrations/woocommerce/connect",
        data={"store_url": "https://example-store.com", "consumer_key": "ck_right", "consumer_secret": "cs_right"},
    )

    with patch("app.test_connection", return_value=(True, "Connection successful.")):
        logged_in_client.post("/integrations/woocommerce/test")

    integration = db.get_integration(user_id, "ecommerce")
    assert integration["connection_status"] == "connected"


# ---------- 19: Admin authorization ----------

def test_normal_user_forbidden_from_admin_dashboard(logged_in_client):
    response = logged_in_client.get("/admin")
    assert response.status_code == 403


def test_normal_user_forbidden_logs_security_event(logged_in_client):
    logged_in_client.get("/admin")
    logs = db.get_logs(log_type="security")
    assert any("Unauthorized admin access" in log["message"] for log in logs)


def test_admin_user_can_access_admin_dashboard(admin_client):
    response = admin_client.get("/admin")
    assert response.status_code == 200


def test_admin_cannot_disable_own_account(admin_client):
    admin_id = admin_client.test_user_id
    admin_client.post(f"/admin/users/{admin_id}/toggle-disabled", follow_redirects=True)
    assert db.is_user_disabled(admin_id) is False


def test_admin_can_disable_other_user(admin_client):
    other_user_id = db.find_or_create_google_user("g-other", "Other User", "other@example.com")
    admin_client.post(f"/admin/users/{other_user_id}/toggle-disabled")
    assert db.is_user_disabled(other_user_id) is True


# ---- Security fix (audit issue #3): admin authorization must never trust the session ----

def test_normal_user_cannot_access_admin_functionality(logged_in_client):
    response = logged_in_client.get("/admin")
    assert response.status_code == 403

    response = logged_in_client.get("/admin/users")
    assert response.status_code == 403


def test_actual_admin_can_access_admin_functionality(admin_client):
    response = admin_client.get("/admin")
    assert response.status_code == 200

    response = admin_client.get("/admin/users")
    assert response.status_code == 200


def test_tampered_session_is_admin_flag_does_not_grant_access(logged_in_client):
    """
    The core of audit issue #3: a normal user manually sets is_admin=True in
    their own session (simulating either a client-side tamper attempt or a
    stale value from before being demoted). Since admin_required now checks
    the database on every request instead of trusting the session, this
    must NOT grant access.
    """
    with logged_in_client.session_transaction() as sess:
        sess["is_admin"] = True  # forged/stale value — the DB still says False

    response = logged_in_client.get("/admin")
    assert response.status_code == 403

    response = logged_in_client.get("/admin/users")
    assert response.status_code == 403

    # Also confirm the attempt was still logged as unauthorized, same as any
    # other non-admin trying to reach an admin route.
    logs = db.get_logs(log_type="security")
    assert any("Unauthorized admin access" in log["message"] for log in logs)


def test_disabled_user_logged_out_on_next_request(client):
    user_id = db.find_or_create_google_user("g-disabled", "Disabled User", "disabled@example.com")
    db.set_user_disabled(user_id, True)

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["is_admin"] = False

    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]