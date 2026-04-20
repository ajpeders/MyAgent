"""SQLite-backed user, email cache, and session storage.

Consolidates all persistent storage into a single SQLite database.
IMAP credentials and email caches are encrypted at rest using AES-256-GCM
with keys derived from the user's password.
"""
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import sqlite3

from core.crypto import decrypt_payload, encrypt_payload, hash_password, verify_password

DB_PATH = Path(__file__).parent / "data.db"

_schema_initialized = False


def _connect() -> sqlite3.Connection:
    """Connect to DB with WAL mode and busy timeout."""
    global _schema_initialized
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    if not _schema_initialized:
        _init_schema(conn)
        _schema_initialized = True

    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and run migrations. Called once per process."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id              TEXT PRIMARY KEY,
            email                TEXT UNIQUE NOT NULL,
            password_hash        TEXT,
            encrypted_imap_creds BLOB,
            created_at           REAL NOT NULL,
            updated_at           REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_cache (
            user_id        TEXT NOT NULL,
            account_name   TEXT NOT NULL,
            mailbox        TEXT NOT NULL,
            encrypted_blob BLOB NOT NULL,
            updated_at     REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE(user_id, account_name, mailbox)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            mail_engine   TEXT,
            imap_accounts TEXT,
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing tables that predate schema changes."""
    migrations = [
        ("ALTER TABLE users ADD COLUMN password_hash TEXT", "users.password_hash"),
        ("ALTER TABLE sessions ADD COLUMN imap_accounts TEXT", "sessions.imap_accounts"),
        ("ALTER TABLE sessions ADD COLUMN pending TEXT", "sessions.pending"),
    ]
    for sql, _ in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


# ── User Store ────────────────────────────────────────────────────────────────


class UserStore:
    """Manages user identity and encrypted IMAP credentials."""

    def create_user(self, email: str, password: str) -> str:
        """Create a user row with a hashed password. Returns user_id."""
        user_id = str(uuid.uuid4())
        now = time.time()
        pw_hash = json.dumps(hash_password(password))
        conn = _connect()
        conn.execute(
            "INSERT INTO users (user_id, email, password_hash, encrypted_imap_creds, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email.lower(), pw_hash, None, now, now),
        )
        conn.commit()
        conn.close()
        return user_id

    def verify_password(self, user_id: str, password: str) -> bool:
        """Return True if the password matches the stored hash."""
        user = self.get_user_by_id(user_id)
        if not user or not user["password_hash"]:
            return False
        stored = json.loads(user["password_hash"])
        return verify_password(password, stored)

    def get_user_by_email(self, email: str) -> dict | None:
        """Return user row or None."""
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds FROM users WHERE email = ?",
            (email.lower(),),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "encrypted_imap_creds": row[3],
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        """Return user row or None."""
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "encrypted_imap_creds": row[3],
        }

    def update_imap_creds(self, user_id: str, encrypted_creds: list) -> None:
        """Atomically update user's encrypted IMAP credentials."""
        now = time.time()
        blob = json.dumps(encrypted_creds).encode()
        conn = _connect()
        conn.execute(
            "UPDATE users SET encrypted_imap_creds = ?, updated_at = ? WHERE user_id = ?",
            (blob, now, user_id),
        )
        conn.commit()
        conn.close()

    def delete_user(self, user_id: str) -> None:
        """Delete user and all associated data (cascades to sessions/email_cache)."""
        conn = _connect()
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def list_users(self) -> list[dict]:
        """Return all users (without sensitive fields)."""
        conn = _connect()
        rows = conn.execute(
            "SELECT user_id, email, created_at, updated_at FROM users"
        ).fetchall()
        conn.close()
        return [
            {"user_id": r[0], "email": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def count_users(self) -> int:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return count


# ── Email Cache Store ─────────────────────────────────────────────────────────


class EmailCacheStore:
    """Manages encrypted email caches per user/account/mailbox."""

    def get_cached_emails(
        self, user_id: str, account_name: str, mailbox: str, password: str
    ) -> list[dict] | None:
        """Return decrypted email list from cache, or None if missing.

        Raises ValueError if decryption fails (wrong password).
        """
        conn = _connect()
        row = conn.execute(
            "SELECT encrypted_blob, updated_at FROM email_cache WHERE user_id = ? AND account_name = ? AND mailbox = ?",
            (user_id, account_name, mailbox),
        ).fetchone()
        conn.close()
        if not row:
            return None
        encrypted_blob = row[0]
        if isinstance(encrypted_blob, str):
            encrypted_blob = encrypted_blob.encode()
        import base64
        encrypted = base64.b64decode(encrypted_blob)
        import json as json_mod
        inner = json_mod.loads(encrypted)
        return decrypt_payload(inner, password)

    def set_cached_emails(
        self, user_id: str, account_name: str, mailbox: str, emails: list[dict], password: str
    ) -> None:
        """Encrypt emails with user's password and store in cache."""
        now = time.time()
        encrypted = encrypt_payload(emails, password)
        import base64
        blob = base64.b64encode(json.dumps(encrypted).encode())
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO email_cache (user_id, account_name, mailbox, encrypted_blob, updated_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, account_name, mailbox, blob, now),
        )
        conn.commit()
        conn.close()

    def invalidate(self, user_id: str, account_name: str, mailbox: str) -> None:
        """Delete cache entry."""
        conn = _connect()
        conn.execute(
            "DELETE FROM email_cache WHERE user_id = ? AND account_name = ? AND mailbox = ?",
            (user_id, account_name, mailbox),
        )
        conn.commit()
        conn.close()


# ── Session State ─────────────────────────────────────────────────────────────


@dataclass
class SessionState:
    """Persistent session state — identity and mail inbox only."""
    session_id: str = ""
    user_id: str = ""
    mail_engine: dict | None = None
    imap_accounts: list[dict] | None = None  # decrypted at login, available for IMAP ops
    pending: dict | None = None  # pending action awaiting confirmation


class SessionStore:
    """Manages conversation sessions linked to users."""

    def create_session(self, user_id: str, imap_accounts: list[dict] | None = None) -> str:
        """Create a new session for a user. Returns session_id."""
        session_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, imap_accounts, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, json.dumps(imap_accounts) if imap_accounts else None, now, now),
        )
        conn.commit()
        conn.close()
        return session_id

    def get_session(self, session_id: str) -> SessionState | None:
        """Load session state, or None if not found."""
        conn = _connect()
        row = conn.execute(
            "SELECT session_id, user_id, mail_engine, imap_accounts, pending FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return SessionState(
            session_id=row[0],
            user_id=row[1],
            mail_engine=json.loads(row[2]) if row[2] else None,
            imap_accounts=json.loads(row[3]) if row[3] else None,
            pending=json.loads(row[4]) if row[4] else None,
        )

    def save_session(self, state: SessionState) -> None:
        """Persist session state."""
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, user_id, mail_engine, imap_accounts, pending, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                state.session_id,
                state.user_id,
                json.dumps(state.mail_engine) if state.mail_engine else None,
                json.dumps(state.imap_accounts) if state.imap_accounts else None,
                json.dumps(state.pending) if state.pending else None,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def delete_session(self, session_id: str) -> None:
        """Delete session."""
        conn = _connect()
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def get_sessions_for_user(self, user_id: str) -> list[SessionState]:
        """List all sessions for a user."""
        conn = _connect()
        rows = conn.execute(
            "SELECT session_id, user_id, mail_engine, imap_accounts FROM sessions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()
        return [
            SessionState(
                session_id=r[0],
                user_id=r[1],
                mail_engine=json.loads(r[2]) if r[2] else None,
                imap_accounts=json.loads(r[3]) if r[3] else None,
            )
            for r in rows
        ]

    def count_sessions(self) -> int:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        return count

    def list_sessions(self) -> list[dict]:
        """Return all sessions (metadata only, no credentials)."""
        conn = _connect()
        rows = conn.execute(
            "SELECT session_id, user_id, mail_engine IS NOT NULL, created_at, updated_at FROM sessions"
        ).fetchall()
        conn.close()
        return [
            {
                "session_id": r[0],
                "user_id": r[1],
                "has_mail_engine": bool(r[2]),
                "created_at": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]
