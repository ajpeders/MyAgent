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

from src.core.crypto import decrypt_payload, encrypt_payload, hash_password, verify_password

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
            is_admin             INTEGER NOT NULL DEFAULT 0,
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
            pending       TEXT,
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            memory_id     TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            content       TEXT NOT NULL,
            embedding     BLOB,
            created_at    REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing tables that predate schema changes."""
    migrations = [
        ("ALTER TABLE users ADD COLUMN password_hash TEXT", "users.password_hash"),
        ("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0", "users.is_admin"),
        ("ALTER TABLE sessions ADD COLUMN imap_accounts TEXT", "sessions.imap_accounts"),
        ("ALTER TABLE sessions ADD COLUMN password_hash TEXT", "sessions.password_hash"),
        ("ALTER TABLE sessions ADD COLUMN pending TEXT", "sessions.pending"),
    ]
    for sql, _ in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


__all__ = ["_connect", "_init_schema", "_migrate", "_schema_initialized", "DB_PATH"]