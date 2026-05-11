"""SQLite-backed user, email cache, and session storage.

Consolidates all persistent storage into a single SQLite database.
IMAP credentials and email caches are encrypted at rest using AES-256-GCM
with keys derived from the user's password.
"""
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import sqlite3

from src.core.crypto import decrypt_payload, encrypt_payload, hash_password, verify_password

_DATA_DIR = os.environ.get("MYDEVTEAM_DATA_DIR")
DB_PATH = Path(_DATA_DIR) / "data.db" if _DATA_DIR else Path(__file__).parent / "data.db"

_schema_initialized = False
_schema_initialized_path: str | None = None


def _connect() -> sqlite3.Connection:
    """Connect to DB with WAL mode and busy timeout."""
    global _schema_initialized, _schema_initialized_path
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    current_path = str(DB_PATH)
    if (not _schema_initialized) or (_schema_initialized_path != current_path):
        _init_schema(conn)
        _schema_initialized = True
        _schema_initialized_path = current_path

    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and run migrations. Called once per process."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id              TEXT PRIMARY KEY,
            email                TEXT UNIQUE NOT NULL,
            password_hash        TEXT,
            encrypted_imap_creds BLOB,
            mail_model           TEXT,
            mail_preferences     TEXT,
            search_provider      TEXT,
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
        CREATE TABLE IF NOT EXISTS email_messages (
            message_pk      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            account_name    TEXT NOT NULL,
            mailbox         TEXT NOT NULL,
            uid             INTEGER NOT NULL,
            uidvalidity     TEXT NOT NULL DEFAULT '',
            message_id      TEXT,
            sort_rank       INTEGER NOT NULL DEFAULT 0,
            synced_at       REAL NOT NULL,
            encrypted_blob  BLOB NOT NULL,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE(user_id, account_name, mailbox, uidvalidity, uid)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_sync_state (
            user_id         TEXT NOT NULL,
            account_name    TEXT NOT NULL,
            mailbox         TEXT NOT NULL,
            uidvalidity     TEXT NOT NULL DEFAULT '',
            last_synced_at  REAL NOT NULL,
            last_count      INTEGER NOT NULL DEFAULT 0,
            last_error      TEXT,
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS device_tokens (
            token_id     TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL UNIQUE,
            token_hash   TEXT NOT NULL,
            last4        TEXT NOT NULL,
            created_at   REAL NOT NULL,
            last_used_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_device_tokens_hash
        ON device_tokens (token_hash)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS whisper_transcripts (
            transcript_id    TEXT PRIMARY KEY,
            user_id          TEXT NOT NULL,
            source           TEXT NOT NULL,
            text             TEXT NOT NULL,
            language         TEXT,
            duration_seconds REAL,
            segments_json    TEXT,
            model            TEXT NOT NULL,
            captured_at      REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_whisper_transcripts_user
        ON whisper_transcripts (user_id, captured_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voice_jobs (
            job_id        TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            status        TEXT NOT NULL,
            source        TEXT NOT NULL,
            transcript    TEXT,
            tool          TEXT,
            args_json     TEXT,
            result_json   TEXT,
            reply         TEXT,
            error         TEXT,
            created_at    REAL NOT NULL,
            completed_at  REAL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voice_jobs_user
        ON voice_jobs (user_id, created_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_actions (
            action_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            action          TEXT NOT NULL,
            email_from      TEXT,
            email_subject   TEXT,
            email_date      TEXT,
            email_account   TEXT,
            email_uid       INTEGER,
            ai_recommendation TEXT,
            ai_summary      TEXT,
            feedback_text   TEXT,
            created_at      REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_email_actions_user
        ON email_actions (user_id, created_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_email_messages_scope
        ON email_messages (user_id, account_name, mailbox, synced_at DESC, sort_rank ASC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_email_messages_message_id
        ON email_messages (user_id, message_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_email_sync_state_recent
        ON email_sync_state (user_id, last_synced_at DESC)
    """)
    conn.commit()
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing tables that predate schema changes."""
    migrations = [
        ("ALTER TABLE users ADD COLUMN password_hash TEXT", "users.password_hash"),
        ("ALTER TABLE users ADD COLUMN mail_model TEXT", "users.mail_model"),
        ("ALTER TABLE users ADD COLUMN mail_preferences TEXT", "users.mail_preferences"),
        ("ALTER TABLE users ADD COLUMN search_provider TEXT", "users.search_provider"),
        ("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0", "users.is_admin"),
        ("ALTER TABLE sessions ADD COLUMN imap_accounts TEXT", "sessions.imap_accounts"),
        ("ALTER TABLE sessions ADD COLUMN password_hash TEXT", "sessions.password_hash"),
        ("ALTER TABLE sessions ADD COLUMN pending TEXT", "sessions.pending"),
        ("ALTER TABLE email_actions ADD COLUMN feedback_text TEXT", "email_actions.feedback_text"),
    ]
    for sql, _ in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


__all__ = ["_connect", "_init_schema", "_migrate", "_schema_initialized", "_schema_initialized_path", "DB_PATH"]
