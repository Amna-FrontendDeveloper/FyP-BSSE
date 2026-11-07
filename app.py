import logging
import os
from hmac import compare_digest
from functools import wraps
from secrets import token_urlsafe

from flask import Flask, abort, render_template, request, jsonify, session, redirect, url_for, flash
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth

load_dotenv()

from database.database import (
    init_db,
    get_or_create_conversation,
    save_message,
    get_today_message_count,
    increment_usage,
    claim_daily_chat_request,
    has_reached_daily_limit,
    find_or_create_google_user,
    get_user_by_id,
    get_conversations_for_user,
    get_conversation_if_owned,
    delete_conversation_if_owned,
    get_integration,
    save_integration,
    save_woocommerce_integration,
    update_connection_status,
    disconnect_integration,
    save_products,
    get_products_for_user,
    mark_conversation_escalated,
    resolve_conversation_if_owned,
    get_escalated_conversations_for_user,
    get_unresolved_escalation_count,
    log_event,
    ensure_admin_by_email,
    is_user_disabled,
    set_user_disabled,
    get_all_users_admin_view,
    get_user_admin_detail,
    get_system_stats,
    get_logs,
    DAILY_MESSAGE_LIMIT,
    DAILY_CHAT_REQUEST_LIMIT,
)
from services.ai_service import get_ai_response
from services.woocommerce_service import test_connection, fetch_products
from services.crypto_utils import encrypt_value, decrypt_value
from services.escalation_service import detect_pre_ai_escalation, detect_post_ai_escalation
from services.product_context_service import build_product_context

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

IS_PRODUCTION = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower() == "production"
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or (IS_PRODUCTION and len(SECRET_KEY) < 32):
    raise RuntimeError(
        "SECRET_KEY must be set and contain at least 32 characters in production. "
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
    )
app.config["SECRET_KEY"] = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    MAX_CONTENT_LENGTH=16 * 1024,
)

init_db()

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

PREMIUM_PLAN_INFO = {
    "message": "You've reached today's free limit of 100 AI messages.",
    "plan_name": "Premium Plan",
    "plan_benefit": "Unlimited daily AI messages and priority response times.",
    "plan_features": [
        "Unlimited daily AI messages",
        "Priority response times",
        "WhatsApp and e-commerce integration support",
        "Conversation history and customer-support tools",
    ],
    "cta": "Premium checkout is not enabled yet. Contact the project administrator for plan information.",
}

MAX_CHAT_MESSAGE_LENGTH = 2000


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token}


@app.before_request
def protect_state_changing_requests():
    if (
        not app.config.get("CSRF_ENABLED", True)
        or request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}
        or not session.get("user_id")
    ):
        return

    expected = session.get("_csrf_token")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not expected or not supplied or not compare_digest(expected, supplied):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Invalid or missing CSRF token."}), 400
        abort(400)


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in to continue."}), 401
            return redirect(url_for("login_page"))

        if is_user_disabled(session["user_id"]):
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "This account has been disabled."}), 403
            flash("Your account has been disabled. Please contact support.", "error")
            return redirect(url_for("login_page"))

        return view_func(*args, **kwargs)
    return wrapped


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login_page"))

        # Security fix (audit issue #3): is_admin is looked up fresh from the
        # database on every request here, never trusted from the session.
        # A session value can be stale (an admin who was demoted keeps old
        # access until this check) or, in principle, tampered with — the
        # database is the only authoritative source for who is actually an
        # admin right now. This mirrors the disabled-user check just below,
        # which already re-verifies live for the same reason.
        user = get_user_by_id(session["user_id"])
        if not user:
            session.clear()
            return redirect(url_for("login_page"))

        if user["is_disabled"]:
            session.clear()
            flash("Your account has been disabled.", "error")
            return redirect(url_for("login_page"))

        if not user["is_admin"]:
            logger.warning("Unauthorized admin access attempt by user_id=%s", session.get("user_id"))
            log_event("security", "Unauthorized admin access attempt", session.get("user_id"))
            return "Forbidden: admin access only.", 403

        # Keep the session's is_admin flag in sync with the real value too,
        # so UI elements (e.g. the sidebar's Admin link) stay accurate —
        # this is a display convenience only; it is never what grants access.
        session["is_admin"] = True
        return view_func(*args, **kwargs)
    return wrapped


@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/login/google")
def login_google():
    redirect_uri = url_for("auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/callback")
def auth_callback():
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        logger.exception("Google OAuth callback failed")
        return redirect(url_for("login_page"))

    userinfo = token.get("userinfo")
    if not userinfo:
        return redirect(url_for("login_page"))

    google_id = userinfo.get("sub")
    name = userinfo.get("name") or "Google User"
    email = userinfo.get("email")

    if not google_id or not email:
        return redirect(url_for("login_page"))

    user_id = find_or_create_google_user(google_id, name, email)
    ensure_admin_by_email(email)

    if is_user_disabled(user_id):
        flash("Your account has been disabled.", "error")
        return redirect(url_for("login_page"))

    user = get_user_by_id(user_id)

    session.clear()
    session["user_id"] = user_id
    session["user_name"] = name
    session["is_admin"] = bool(user["is_admin"]) if user else False

    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/")
@login_required
def dashboard():
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    messages_used_today = get_today_message_count(user_id)
    remaining_messages = max(DAILY_MESSAGE_LIMIT - messages_used_today, 0)
    unresolved_escalations = get_unresolved_escalation_count(user_id)

    return render_template(
        "dashboard.html",
        active_page="overview",
        user=user,
        messages_used_today=messages_used_today,
        remaining_messages=remaining_messages,
        unresolved_escalations=unresolved_escalations,
    )


@app.route("/chat")
@login_required
def chat_page():
    return render_template("chat.html", active_page="chat")


@app.route("/conversations")
@login_required
def conversations_page():
    conversations = get_conversations_for_user(session["user_id"])
    return render_template("conversations.html", active_page="conversations", conversations=conversations)


@app.route("/conversations/<int:conversation_id>")
@login_required
def conversation_detail_page(conversation_id):
    conversation, messages = get_conversation_if_owned(conversation_id, session["user_id"])
    if not conversation:
        return redirect(url_for("conversations_page"))
    return render_template(
        "conversation_detail.html",
        active_page="conversations",
        conversation=conversation,
        messages=messages,
    )


@app.route("/conversations/<int:conversation_id>/delete", methods=["POST"])
@login_required
def delete_conversation_route(conversation_id):
    delete_conversation_if_owned(conversation_id, session["user_id"])
    return redirect(url_for("conversations_page"))


@app.route("/conversations/<int:conversation_id>/resolve", methods=["POST"])
@login_required
def resolve_conversation_route(conversation_id):
    resolve_conversation_if_owned(conversation_id, session["user_id"])
    return redirect(request.referrer or url_for("escalations_page"))


@app.route("/escalations")
@login_required
def escalations_page():
    escalations = get_escalated_conversations_for_user(session["user_id"])
    return render_template("escalations.html", active_page="escalations", escalations=escalations)


@app.route("/integrations")
@login_required
def integrations_page():
    user_id = session["user_id"]
    whatsapp = get_integration(user_id, "whatsapp")
    ecommerce = get_integration(user_id, "ecommerce")
    products = get_products_for_user(user_id) if ecommerce and ecommerce.get("connection_status") == "connected" else []
    return render_template(
        "integrations.html",
        active_page="integrations",
        whatsapp=whatsapp,
        ecommerce=ecommerce,
        products=products,
    )


@app.route("/integrations/whatsapp", methods=["POST"])
@login_required
def save_whatsapp_integration():
    user_id = session["user_id"]
    existing = get_integration(user_id, "whatsapp")
    phone_number = (request.form.get("phone_number") or "").strip()
    submitted_key = (request.form.get("api_key") or "").strip()
    api_key = submitted_key if submitted_key else (existing["api_key"] if existing else None)
    save_integration(user_id, "whatsapp", phone_number=phone_number, api_key=api_key)
    return redirect(url_for("integrations_page"))


@app.route("/integrations/woocommerce/connect", methods=["POST"])
@login_required
def connect_woocommerce():
    user_id = session["user_id"]
    store_url = (request.form.get("store_url") or "").strip()
    consumer_key = (request.form.get("consumer_key") or "").strip()
    consumer_secret = (request.form.get("consumer_secret") or "").strip()

    if not store_url or not consumer_key or not consumer_secret:
        flash("All three fields are required.", "error")
        return redirect(url_for("integrations_page"))

    if not store_url.startswith("https://"):
        flash("Store URL must start with https://", "error")
        return redirect(url_for("integrations_page"))

    encrypted_key = encrypt_value(consumer_key)
    encrypted_secret = encrypt_value(consumer_secret)
    save_woocommerce_integration(user_id, store_url, encrypted_key, encrypted_secret)
    flash("Store details saved.", "success")
    return redirect(url_for("integrations_page"))


@app.route("/integrations/woocommerce/test", methods=["POST"])
@login_required
def test_woocommerce_connection():
    user_id = session["user_id"]
    integration = get_integration(user_id, "ecommerce")
    if not integration or not integration.get("api_key"):
        flash("Connect your WooCommerce store first.", "error")
        return redirect(url_for("integrations_page"))

    consumer_key = decrypt_value(integration["api_key"])
    consumer_secret = decrypt_value(integration["api_secret"])
    success, message = test_connection(integration["store_url"], consumer_key, consumer_secret)
    update_connection_status(user_id, "ecommerce", "connected" if success else "failed")
    flash(message, "success" if success else "error")
    return redirect(url_for("integrations_page"))


@app.route("/integrations/woocommerce/fetch-products", methods=["POST"])
@login_required
def fetch_woocommerce_products():
    user_id = session["user_id"]
    integration = get_integration(user_id, "ecommerce")
    if not integration or integration.get("connection_status") != "connected":
        flash("Test the connection first.", "error")
        return redirect(url_for("integrations_page"))

    consumer_key = decrypt_value(integration["api_key"])
    consumer_secret = decrypt_value(integration["api_secret"])
    success, result = fetch_products(integration["store_url"], consumer_key, consumer_secret)
    if not success:
        flash(result, "error")
        return redirect(url_for("integrations_page"))

    save_products(user_id, result)
    flash(f"Fetched and saved {len(result)} products.", "success")
    return redirect(url_for("integrations_page"))


@app.route("/integrations/woocommerce/disconnect", methods=["POST"])
@login_required
def disconnect_woocommerce():
    disconnect_integration(session["user_id"], "ecommerce")
    flash("Disconnected.", "success")
    return redirect(url_for("integrations_page"))


@app.route("/profile")
@login_required
def profile_page():
    return render_template("profile.html", active_page="profile", user=get_user_by_id(session["user_id"]))


@app.route("/subscription")
@login_required
def subscription_page():
    messages_used_today = get_today_message_count(session["user_id"])
    remaining_messages = max(DAILY_MESSAGE_LIMIT - messages_used_today, 0)
    return render_template(
        "subscription.html",
        active_page="subscription",
        messages_used_today=messages_used_today,
        remaining_messages=remaining_messages,
        daily_message_limit=DAILY_MESSAGE_LIMIT,
        premium_plan=PREMIUM_PLAN_INFO,
    )


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = get_system_stats()
    return render_template("admin/dashboard.html", active_page="admin", stats=stats)


@app.route("/admin/users")
@admin_required
def admin_users_page():
    users = get_all_users_admin_view()
    return render_template("admin/users.html", active_page="admin", users=users)


@app.route("/admin/users/<int:user_id>")
@admin_required
def admin_user_detail_page(user_id):
    detail = get_user_admin_detail(user_id)
    if not detail:
        flash("User not found.", "error")
        return redirect(url_for("admin_users_page"))
    return render_template("admin/user_detail.html", active_page="admin", detail=detail)


@app.route("/admin/users/<int:user_id>/toggle-disabled", methods=["POST"])
@admin_required
def admin_toggle_user_disabled(user_id):
    if user_id == session["user_id"]:
        flash("You cannot disable your own admin account.", "error")
        return redirect(url_for("admin_user_detail_page", user_id=user_id))

    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin_users_page"))

    new_state = not bool(target["is_disabled"])
    set_user_disabled(user_id, new_state)
    action = "disabled" if new_state else "enabled"
    log_event("activity", f"Admin {session.get('user_name')} {action} user {target['email']}", session["user_id"])
    flash(f"User {target['email']} has been {action}.", "success")
    return redirect(url_for("admin_user_detail_page", user_id=user_id))


@app.route("/admin/logs")
@admin_required
def admin_logs_page():
    log_type = request.args.get("type")
    logs = get_logs(log_type=log_type)
    return render_template("admin/logs.html", active_page="admin", logs=logs, current_filter=log_type)


@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    try:
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()

        if not user_message:
            return jsonify({"error": "Message cannot be empty."}), 400

        if len(user_message) > MAX_CHAT_MESSAGE_LENGTH:
            return jsonify({"error": f"Message cannot exceed {MAX_CHAT_MESSAGE_LENGTH} characters."}), 413

        user_id = session["user_id"]
        if not claim_daily_chat_request(user_id):
            return jsonify({
                "error": "Daily chat request limit reached. Please try again tomorrow.",
                "request_limit_reached": True,
                "daily_request_limit": DAILY_CHAT_REQUEST_LIMIT,
            }), 429

        pre_escalate, pre_reason = detect_pre_ai_escalation(user_message)

        if not pre_escalate and has_reached_daily_limit(user_id):
            return jsonify({
                "error": PREMIUM_PLAN_INFO["message"],
                "limit_reached": True,
                "premium_info": PREMIUM_PLAN_INFO,
                "messages_used_today": DAILY_MESSAGE_LIMIT,
                "daily_limit": DAILY_MESSAGE_LIMIT,
            }), 429

        conversation_id = get_or_create_conversation(user_id)
        save_message(conversation_id, "user", user_message)

        if pre_escalate:
            handoff_reply = "Thanks for reaching out — I've flagged this conversation for our support team."
            save_message(conversation_id, "assistant", handoff_reply)
            mark_conversation_escalated(conversation_id, pre_reason)
            return jsonify({
                "reply": handoff_reply,
                "escalated": True,
                "escalation_reason": pre_reason,
                "messages_used_today": get_today_message_count(user_id),
                "daily_limit": DAILY_MESSAGE_LIMIT,
            })

        ecommerce = get_integration(user_id, "ecommerce")
        products = get_products_for_user(user_id) if ecommerce and ecommerce.get("connection_status") == "connected" else []
        product_context, context_mode = build_product_context(products, user_message)

        success, ai_reply = get_ai_response(user_message, product_context, context_mode)
        save_message(conversation_id, "assistant", ai_reply)

        escalated = False
        if success:
            increment_usage(user_id)
            post_escalate, post_reason = detect_post_ai_escalation(ai_reply)
            if post_escalate:
                mark_conversation_escalated(conversation_id, post_reason)
                escalated = True

        messages_used_today = get_today_message_count(user_id)

        if not success:
            log_event("error", f"AI service failure: {ai_reply}", user_id)
            return jsonify({
                "error": ai_reply,
                "messages_used_today": messages_used_today,
                "daily_limit": DAILY_MESSAGE_LIMIT,
            }), 502

        return jsonify({
            "reply": ai_reply,
            "escalated": escalated,
            "messages_used_today": messages_used_today,
            "daily_limit": DAILY_MESSAGE_LIMIT,
        })

    except Exception:
        logger.exception("Unexpected error in /api/chat")
        log_event("error", "Unexpected error in /api/chat", session.get("user_id"))
        return jsonify({"error": "Something went wrong on our end. Please try again."}), 500


if __name__ == "__main__":
    if IS_PRODUCTION:
        # Never launch via Flask's built-in dev server in production, even
        # by accident — fail loudly instead of quietly serving traffic
        # through an unsafe, single-threaded development server.
        raise RuntimeError(
            "Refusing to start: FLASK_ENV=production, but this file was launched "
            "with 'python app.py', which runs Flask's development server. Use a "
            "production WSGI server instead, e.g.: "
            "gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app"
        )

    debug_mode = not IS_PRODUCTION and os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)