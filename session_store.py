"""SQLite-backed session persistence for mac-agent server."""
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

DB_PATH = Path(__file__).parent / "sessions.db"


@dataclass
class SessionState:
    session_id: str
    model: str
    active_agent: str | None = None          # currently active subagent name
    contexts: dict[str, list[dict]] = field(default_factory=dict)  # agent_name → messages
    inbox: list[dict] = field(default_factory=list)
    pending: dict | None = None              # serialized Action awaiting confirmation


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            data       TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def load_session(session_id: str, model: str) -> SessionState:
    conn = _connect()
    row = conn.execute(
        "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    if row:
        data = json.loads(row[0])
        return SessionState(**data)
    return SessionState(session_id=session_id, model=model)


def save_session(state: SessionState) -> None:
    data = json.dumps({
        "session_id": state.session_id,
        "model": state.model,
        "active_agent": state.active_agent,
        "contexts": state.contexts,
        "inbox": state.inbox,
        "pending": state.pending,
    })
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, data, updated_at) VALUES (?, ?, ?)",
        (state.session_id, data, time.time()),
    )
    conn.commit()
    conn.close()


def delete_session(session_id: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
