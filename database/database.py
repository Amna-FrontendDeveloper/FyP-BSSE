import os
import sqlite3
from pathlib import Path
from datetime import date
import uuid


BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_database_path(configured_path):
    """Resolve relative database paths from the project root."""
    path = Path(configured_path).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


DATABASE_PATH = _resolve_database_path(
    os.getenv("DATABASE_PATH") or "database/app.db"
)

DAILY_MESSAGE_LIMIT = 100
DAILY_CHAT_REQUEST_LIMIT = 200


def get_db_connection():
    database_path = Path(DATABASE_PATH)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _ensure_column(connection, table, column, coltype):
    existing_columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in existing_columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    connection = get_db_connection()

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            store_url TEXT,
            api_key TEXT,
            phone_number TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        );
                CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            external_product_id TEXT NOT NULL,
            name TEXT,
            price TEXT,
            stock_status TEXT,
            description TEXT,
            sku TEXT,
            variations TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            UNIQUE(user_id, external_product_id)
        );

  

        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,

            UNIQUE(user_id, date)
        );

                CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_type TEXT NOT NULL,
            message TEXT NOT NULL,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        );

    """)

    connection.commit()

    _ensure_column(connection, "users", "is_admin", "INTEGER DEFAULT 0")
    _ensure_column(connection, "users", "is_disabled", "INTEGER DEFAULT 0")
    _ensure_column(connection, "integrations", "store_platform", "TEXT")
    _ensure_column(connection, "integrations", "api_secret", "TEXT")
    _ensure_column(connection, "integrations", "connection_status", "TEXT")
    _ensure_column(connection, "integrations", "last_tested_at", "TIMESTAMP")
    _ensure_column(connection, "conversations", "escalated", "INTEGER DEFAULT 0")
    _ensure_column(connection, "conversations", "escalation_reason", "TEXT")
    _ensure_column(connection, "conversations", "needs_human", "INTEGER DEFAULT 0")
    _ensure_column(connection, "conversations", "resolved", "INTEGER DEFAULT 0")
    _ensure_column(connection, "usage", "request_count", "INTEGER DEFAULT 0")
    connection.commit()

    connection.close()


# ---- Added for Step 5: AI Chat MVP ----

def get_or_create_guest_user(existing_user_id=None):
    """
    No login system exists yet (that's Phase 6). Each browser session
    gets its own anonymous 'guest' user row the first time it chats,
    so conversations/messages/usage still have a valid user_id to attach to.
    """
    connection = get_db_connection()

    if existing_user_id is not None:
        row = connection.execute(
            "SELECT id FROM users WHERE id = ?", (existing_user_id,)
        ).fetchone()
        if row:
            connection.close()
            return existing_user_id

    guest_email = f"guest-{uuid.uuid4().hex}@local.guest"
    cursor = connection.execute(
        "INSERT INTO users (google_id, name, email) VALUES (NULL, ?, ?)",
        ("Guest", guest_email),
    )
    connection.commit()
    new_user_id = cursor.lastrowid
    connection.close()
    return new_user_id


def get_or_create_conversation(user_id):
    """MVP keeps one ongoing conversation per user (no 'new chat' button yet)."""
    connection = get_db_connection()
    row = connection.execute(
        "SELECT id FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    if row:
        conversation_id = row["id"]
    else:
        cursor = connection.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (user_id, "New Conversation"),
        )
        connection.commit()
        conversation_id = cursor.lastrowid

    connection.close()
    return conversation_id


def save_message(conversation_id, sender, message):
    """sender must be 'user' or 'assistant'."""
    connection = get_db_connection()
    connection.execute(
        "INSERT INTO messages (conversation_id, sender, message) VALUES (?, ?, ?)",
        (conversation_id, sender, message),
    )
    connection.commit()
    connection.close()


def mark_conversation_escalated(conversation_id, reason):
    connection = get_db_connection()
    connection.execute(
        "UPDATE conversations SET escalated = 1, escalation_reason = ? WHERE id = ?",
        (reason, conversation_id),
    )
    connection.commit()
    connection.close()


def get_unresolved_escalation_count(user_id):
    connection = get_db_connection()
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM conversations "
        "WHERE user_id = ? AND escalated = 1",
        (user_id,),
    ).fetchone()
    connection.close()
    return row["count"]


def get_today_message_count(user_id):
    today = date.today().isoformat()
    connection = get_db_connection()
    row = connection.execute(
        "SELECT message_count FROM usage WHERE user_id = ? AND date = ?",
        (user_id, today),
    ).fetchone()
    connection.close()
    return row["message_count"] if row else 0


def increment_usage(user_id):
    today = date.today().isoformat()
    connection = get_db_connection()
    connection.execute(
        """
        INSERT INTO usage (user_id, date, message_count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, date)
        DO UPDATE SET message_count = message_count + 1
        """,
        (user_id, today),
    )
    connection.commit()
    connection.close()


def has_reached_daily_limit(user_id):
    return get_today_message_count(user_id) >= DAILY_MESSAGE_LIMIT


def claim_daily_chat_request(user_id):
    today = date.today().isoformat()
    connection = get_db_connection()
    cursor = connection.execute(
        """
        INSERT INTO usage (user_id, date, message_count, request_count)
        VALUES (?, ?, 0, 1)
        ON CONFLICT(user_id, date)
        DO UPDATE SET request_count = request_count + 1
        WHERE request_count < ?
        """,
        (user_id, today, DAILY_CHAT_REQUEST_LIMIT),
    )
    connection.commit()
    claimed = cursor.rowcount == 1
    connection.close()
    return claimed


def find_or_create_google_user(google_id, name, email):
    """
    Looks up a user by their Google ID. If not found, checks by email
    (covers the rare case where a row exists without a google_id yet).
    Otherwise creates a new row. Ensures Google users are never duplicated.
    """
    connection = get_db_connection()

    row = connection.execute(
        "SELECT id FROM users WHERE google_id = ?", (google_id,)
    ).fetchone()

    if row:
        user_id = row["id"]
    else:
        existing_email_row = connection.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()

        if existing_email_row:
            connection.execute(
                "UPDATE users SET google_id = ?, name = ? WHERE id = ?",
                (google_id, name, existing_email_row["id"]),
            )
            connection.commit()
            user_id = existing_email_row["id"]
        else:
            cursor = connection.execute(
                "INSERT INTO users (google_id, name, email) VALUES (?, ?, ?)",
                (google_id, name, email),
            )
            connection.commit()
            user_id = cursor.lastrowid

    connection.close()
    return user_id


# ---- Added for Dashboard step ----

def get_user_by_id(user_id):
    connection = get_db_connection()
    row = connection.execute(
        "SELECT id, name, email, created_at, is_admin, is_disabled FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def get_conversations_for_user(user_id):
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT c.id, c.title, c.created_at,
               (SELECT message FROM messages m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_message,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
        FROM conversations c
        WHERE c.user_id = ?
        ORDER BY c.id DESC
        """,
        (user_id,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_conversation_if_owned(conversation_id, user_id):
    """Ownership check built in — a user can never open or see another user's conversation."""
    connection = get_db_connection()
    convo = connection.execute(
        "SELECT id, title, created_at FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id),
    ).fetchone()

    if not convo:
        connection.close()
        return None, []

    messages = connection.execute(
        "SELECT sender, message, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    connection.close()
    return dict(convo), [dict(m) for m in messages]


def delete_conversation_if_owned(conversation_id, user_id):
    connection = get_db_connection()
    cursor = connection.execute(
        "DELETE FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id),
    )
    connection.commit()
    deleted = cursor.rowcount > 0
    connection.close()
    return deleted


def get_escalated_conversations_for_user(user_id):
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT id, title, created_at, escalation_reason
        FROM conversations
        WHERE user_id = ? AND escalated = 1
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def resolve_conversation_if_owned(conversation_id, user_id):
    connection = get_db_connection()
    cursor = connection.execute(
        """
        UPDATE conversations
        SET escalated = 0
        WHERE id = ? AND user_id = ?
        """,
        (conversation_id, user_id),
    )
    connection.commit()
    resolved = cursor.rowcount > 0
    connection.close()
    return resolved


def get_integration(user_id, integration_type):
    connection = get_db_connection()
    row = connection.execute(
        "SELECT * FROM integrations WHERE user_id = ? AND type = ?",
        (user_id, integration_type),
    ).fetchone()
    connection.close()
    return dict(row) if row else None


def save_integration(user_id, integration_type, store_url=None, api_key=None, phone_number=None, store_platform=None):
    existing = get_integration(user_id, integration_type)
    connection = get_db_connection()
    if existing:
        connection.execute(
            """
            UPDATE integrations
            SET store_url = ?, api_key = ?, phone_number = ?, store_platform = ?
            WHERE id = ?
            """,
            (store_url, api_key, phone_number, store_platform, existing["id"]),
        )
    else:
        connection.execute(
            """
            INSERT INTO integrations (user_id, type, store_url, api_key, phone_number, store_platform)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, integration_type, store_url, api_key, phone_number, store_platform),
        )
    connection.commit()
    connection.close()

def save_woocommerce_integration(user_id, store_url, encrypted_key, encrypted_secret):
    existing = get_integration(user_id, "ecommerce")
    connection = get_db_connection()
    if existing:
        connection.execute(
            """
            UPDATE integrations
            SET store_url = ?, api_key = ?, api_secret = ?, store_platform = 'woocommerce',
                connection_status = 'not_tested'
            WHERE id = ?
            """,
            (store_url, encrypted_key, encrypted_secret, existing["id"]),
        )
    else:
        connection.execute(
            """
            INSERT INTO integrations (user_id, type, store_url, api_key, api_secret, store_platform, connection_status)
            VALUES (?, 'ecommerce', ?, ?, ?, 'woocommerce', 'not_tested')
            """,
            (user_id, store_url, encrypted_key, encrypted_secret),
        )
    connection.commit()
    connection.close()


def update_connection_status(user_id, integration_type, status):
    connection = get_db_connection()
    connection.execute(
        "UPDATE integrations SET connection_status = ?, last_tested_at = CURRENT_TIMESTAMP WHERE user_id = ? AND type = ?",
        (status, user_id, integration_type),
    )
    connection.commit()
    connection.close()


def disconnect_integration(user_id, integration_type):
    connection = get_db_connection()
    connection.execute(
        "DELETE FROM integrations WHERE user_id = ? AND type = ?",
        (user_id, integration_type),
    )
    connection.commit()
    connection.close()
    delete_products_for_user(user_id)


def save_products(user_id, products):
    connection = get_db_connection()
    for product in products:
        connection.execute(
            """
            INSERT INTO products (user_id, external_product_id, name, price, stock_status, description, sku, variations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, external_product_id)
            DO UPDATE SET name=excluded.name, price=excluded.price, stock_status=excluded.stock_status,
                          description=excluded.description, sku=excluded.sku, variations=excluded.variations,
                          fetched_at=CURRENT_TIMESTAMP
            """,
            (
                user_id,
                product["external_product_id"],
                product["name"],
                product["price"],
                product["stock_status"],
                product["description"],
                product["sku"],
                product["variations"],
            ),
        )
    connection.commit()
    connection.close()


def get_products_for_user(user_id):
    connection = get_db_connection()
    rows = connection.execute(
        "SELECT * FROM products WHERE user_id = ? ORDER BY name ASC",
        (user_id,),
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def delete_products_for_user(user_id):
    connection = get_db_connection()
    connection.execute("DELETE FROM products WHERE user_id = ?", (user_id,))
    connection.commit()
    connection.close()


def log_event(log_type, message, user_id=None):
    connection = get_db_connection()
    connection.execute(
        "INSERT INTO logs (log_type, message, user_id) VALUES (?, ?, ?)",
        (log_type, message, user_id),
    )
    connection.commit()
    connection.close()


def get_logs(log_type=None, limit=200):
    connection = get_db_connection()
    query = """
        SELECT l.id, l.log_type, l.message, l.created_at, u.email as user_email
        FROM logs l
        LEFT JOIN users u ON u.id = l.user_id
    """
    params = ()
    if log_type:
        query += " WHERE l.log_type = ?"
        params = (log_type,)
    query += " ORDER BY l.id DESC LIMIT ?"
    params = params + (limit,)

    rows = connection.execute(query, params).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def ensure_admin_by_email(email):
    """
    Promotes a user to admin if their email is in the ADMIN_EMAILS allowlist.
    Called at login time — there is no in-app way for a user to self-promote.
    """
    connection = get_db_connection()
    connection.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
    connection.commit()
    connection.close()


def is_user_disabled(user_id):
    connection = get_db_connection()
    row = connection.execute("SELECT is_disabled FROM users WHERE id = ?", (user_id,)).fetchone()
    connection.close()
    return bool(row["is_disabled"]) if row else False


def set_user_disabled(user_id, disabled):
    connection = get_db_connection()
    connection.execute("UPDATE users SET is_disabled = ? WHERE id = ?", (1 if disabled else 0, user_id))
    connection.commit()
    connection.close()


def get_all_users_admin_view():
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT u.id, u.name, u.email, u.created_at, u.is_admin, u.is_disabled,
               (SELECT COALESCE(SUM(message_count), 0) FROM usage WHERE user_id = u.id) AS total_messages,
               (SELECT message_count FROM usage WHERE user_id = u.id AND date = date('now')) AS messages_today,
               (SELECT COUNT(*) FROM integrations WHERE user_id = u.id AND type = 'whatsapp' AND phone_number IS NOT NULL) AS has_whatsapp,
               (SELECT connection_status FROM integrations WHERE user_id = u.id AND type = 'ecommerce') AS ecommerce_status
        FROM users u
        ORDER BY u.created_at DESC
        """
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


def get_user_admin_detail(user_id):
    connection = get_db_connection()
    user = connection.execute(
        "SELECT id, name, email, created_at, is_admin, is_disabled FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        connection.close()
        return None

    integrations = connection.execute(
        "SELECT type, store_url, phone_number, store_platform, connection_status FROM integrations WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    total_messages_row = connection.execute(
        "SELECT COALESCE(SUM(message_count), 0) as total FROM usage WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    conversation_count_row = connection.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    connection.close()
    return {
        "user": dict(user),
        "integrations": [dict(i) for i in integrations],
        "total_messages": total_messages_row["total"],
        "conversation_count": conversation_count_row["cnt"],
    }


def get_system_stats():
    connection = get_db_connection()
    stats = {}
    stats["total_users"] = connection.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    stats["disabled_users"] = connection.execute("SELECT COUNT(*) as c FROM users WHERE is_disabled = 1").fetchone()["c"]
    stats["total_conversations"] = connection.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
    stats["total_messages"] = connection.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
    stats["messages_today"] = connection.execute(
        "SELECT COALESCE(SUM(message_count), 0) as c FROM usage WHERE date = date('now')"
    ).fetchone()["c"]
    stats["unresolved_escalations"] = connection.execute(
        "SELECT COUNT(*) as c FROM conversations WHERE needs_human = 1 AND resolved = 0"
    ).fetchone()["c"]
    stats["connected_woocommerce_stores"] = connection.execute(
        "SELECT COUNT(*) as c FROM integrations WHERE type = 'ecommerce' AND connection_status = 'connected'"
    ).fetchone()["c"]
    stats["errors_today"] = connection.execute(
        "SELECT COUNT(*) as c FROM logs WHERE log_type = 'error' AND date(created_at) = date('now')"
    ).fetchone()["c"]
    connection.close()
    return stats


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
