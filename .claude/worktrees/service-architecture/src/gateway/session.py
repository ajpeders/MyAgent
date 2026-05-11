"""Session state management — gateway-owned. Moved from src/core/session_store.py."""
import json
import time
import uuid
from dataclasses import dataclass

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "sessions.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            mail_engine TEXT,
            imap_accounts TEXT,
            pending TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


@dataclass
class SessionState:
    """Persistent session state — identity and mail inbox only."""
    session_id: str = ""
    user_id: str = ""
    mail_engine: dict | None = None
    imap_accounts: list[dict] | None = None
    pending: dict | None = None


class SessionStore:
    """Manages conversation sessions linked to users."""

    def create_session(self, user_id: str, imap_accounts: list[dict] | None = None) -> str:
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
        conn = _connect()
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def get_sessions_for_user(self, user_id: str) -> list[SessionState]:
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


_session_store = SessionStore()


def load_session(session_id: str, user_id: str) -> SessionState:
    state = _session_store.get_session(session_id)
    if not state:
        from services.auth.errors import UserNotFoundError
        raise UserNotFoundError(f"Session {session_id} not found")
    if state.user_id != user_id:
        from services.auth.errors import InvalidCredentialsError
        raise InvalidCredentialsError("Session does not belong to this user")
    return state


def save_session(state: SessionState) -> None:
    _session_store.save_session(state)