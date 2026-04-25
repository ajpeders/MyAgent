"""UserStore moved from core/db.py."""
import json
import time
import uuid

import sqlite3

from src.core.crypto import hash_password, verify_password
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data.db"

_schema_initialized = False


def _connect() -> sqlite3.Connection:
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id              TEXT PRIMARY KEY,
            email                TEXT UNIQUE NOT NULL,
            password_hash        TEXT,
            encrypted_imap_creds BLOB,
            is_admin             INTEGER NOT NULL DEFAULT 0,
            created_at           REAL NOT NULL,
            updated_at           REAL NOT NULL
        )
    """)
    # Migration for existing DBs
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # column already exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            mail_engine   TEXT,
            imap_accounts TEXT,
            enc_key       TEXT,
            password_hash TEXT,
            pending       TEXT,
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.commit()


class UserStore:
    def create_user(self, email: str, password: str) -> str:
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
        user = self.get_user_by_id(user_id)
        if not user or not user["password_hash"]:
            return False
        stored = json.loads(user["password_hash"])
        return verify_password(password, stored)

    def get_user_by_email(self, email: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds, is_admin FROM users WHERE email = ?",
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
            "is_admin": bool(row[4]),
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds, is_admin FROM users WHERE user_id = ?",
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
            "is_admin": bool(row[4]),
        }

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        import time as _time
        conn = _connect()
        conn.execute(
            "UPDATE users SET is_admin = ?, updated_at = ? WHERE user_id = ?",
            (int(is_admin), _time.time(), user_id),
        )
        conn.commit()
        conn.close()

    def update_imap_creds(self, user_id: str, encrypted_creds: list) -> None:
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
        conn = _connect()
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def list_users(self) -> list[dict]:
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