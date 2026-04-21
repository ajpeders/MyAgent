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
import redis

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


SESSION_TTL = 7 * 24 * 3600  # 7 days in seconds


class RedisSessionStore:
    """Redis-backed session store. Sessions auto-expire after SESSION_TTL of inactivity."""

    _pool_instance: redis.ConnectionPool | None = None

    @classmethod
    def _pool(cls) -> redis.ConnectionPool:
        if cls._pool_instance is None:
            from core.config import REDIS_URL

            cls._pool_instance = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
        return cls._pool_instance

    def _client(self) -> redis.Redis:
        return redis.Redis(connection_pool=self._pool())

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}"

    @staticmethod
    def _user_set_key(user_id: str) -> str:
        return f"user_sessions:{user_id}"

    @staticmethod
    def _serialize(val) -> str:
        return json.dumps(val) if val is not None else ""

    @staticmethod
    def _deserialize(raw: str):
        return json.loads(raw) if raw else None

    def create_session(self, user_id: str, imap_accounts: list[dict] | None = None) -> str:
        session_id = str(uuid.uuid4())
        now = time.time()
        client = self._client()
        pipe = client.pipeline()
        pipe.hset(
            self._key(session_id),
            mapping={
                "session_id": session_id,
                "user_id": user_id,
                "mail_engine": "",
                "imap_accounts": self._serialize(imap_accounts),
                "pending": "",
                "created_at": str(now),
            },
        )
        pipe.expire(self._key(session_id), SESSION_TTL)
        pipe.sadd(self._user_set_key(user_id), session_id)
        pipe.execute()
        return session_id

    def get_session(self, session_id: str) -> SessionState | None:
        client = self._client()
        data = client.hgetall(self._key(session_id))
        if not data:
            return None
        client.expire(self._key(session_id), SESSION_TTL)  # reset TTL on access
        return SessionState(
            session_id=data["session_id"],
            user_id=data["user_id"],
            mail_engine=self._deserialize(data.get("mail_engine", "")),
            imap_accounts=self._deserialize(data.get("imap_accounts", "")),
            pending=self._deserialize(data.get("pending", "")),
        )

    def save_session(self, state: SessionState) -> None:
        client = self._client()
        now = time.time()
        key = self._key(state.session_id)
        pipe = client.pipeline()
        pipe.hset(
            key,
            mapping={
                "session_id": state.session_id,
                "user_id": state.user_id,
                "mail_engine": self._serialize(state.mail_engine),
                "imap_accounts": self._serialize(state.imap_accounts),
                "pending": self._serialize(state.pending),
            },
        )
        if not client.hexists(key, "created_at"):
            pipe.hset(key, "created_at", str(now))
        pipe.expire(key, SESSION_TTL)
        pipe.sadd(self._user_set_key(state.user_id), state.session_id)
        pipe.execute()

    def delete_session(self, session_id: str) -> None:
        client = self._client()
        user_id = client.hget(self._key(session_id), "user_id")
        pipe = client.pipeline()
        pipe.delete(self._key(session_id))
        if user_id:
            pipe.srem(self._user_set_key(user_id), session_id)
        pipe.execute()

    def get_sessions_for_user(self, user_id: str) -> list[SessionState]:
        client = self._client()
        session_ids = client.smembers(self._user_set_key(user_id))
        results = []
        for sid in session_ids:
            data = client.hgetall(self._key(sid))
            if data:
                results.append(
                    SessionState(
                        session_id=data["session_id"],
                        user_id=data["user_id"],
                        mail_engine=self._deserialize(data.get("mail_engine", "")),
                        imap_accounts=self._deserialize(data.get("imap_accounts", "")),
                        pending=None,
                    )
                )
        return results

    def count_sessions(self) -> int:
        client = self._client()
        count = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match="session:*", count=100)
            count += len(keys)
            if cursor == 0:
                break
        return count

    def list_sessions(self) -> list[dict]:
        client = self._client()
        sessions = []
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match="session:*", count=100)
            for key in keys:
                data = client.hgetall(key)
                if data:
                    sessions.append(
                        {
                            "session_id": data["session_id"],
                            "user_id": data["user_id"],
                            "has_mail_engine": bool(data.get("mail_engine", "")),
                            "created_at": float(data["created_at"]) if data.get("created_at") else None,
                            "updated_at": None,
                        }
                    )
            if cursor == 0:
                break
        return sessions


# Alias so imports in other modules (e.g. server/__main__.py) work unchanged
SessionStore = RedisSessionStore
