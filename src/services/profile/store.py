"""Profile store — owns user_profile and profile_signals tables in the shared DB."""
import json
import time
import uuid

from src.core.db import _connect


_migrated = False


def _ensure_tables() -> None:
    global _migrated
    if _migrated:
        return
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id      TEXT PRIMARY KEY,
            interests    TEXT,
            model_config TEXT,
            updated_at   REAL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profile_signals (
            signal_id   TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            topic       TEXT NOT NULL,
            source      TEXT NOT NULL,
            created_at  REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_profile_signals_user_created
        ON profile_signals(user_id, created_at DESC)
    """)
    conn.commit()
    conn.close()
    _migrated = True


class ProfileStore:
    def get_interests(self, user_id: str) -> list[str]:
        _ensure_tables()
        conn = _connect()
        row = conn.execute(
            "SELECT interests FROM user_profile WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if row is None or row[0] is None:
            return []
        return json.loads(row[0])

    def set_interests(self, user_id: str, interests: list[str]) -> None:
        _ensure_tables()
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO user_profile (user_id, interests, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET interests = excluded.interests, updated_at = excluded.updated_at",
            (user_id, json.dumps(interests), now),
        )
        conn.commit()
        conn.close()

    def log_signal(self, user_id: str, signal_type: str, topic: str, source: str) -> None:
        _ensure_tables()
        signal_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO profile_signals (signal_id, user_id, signal_type, topic, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (signal_id, user_id, signal_type, topic, source, now),
        )
        conn.commit()
        conn.close()

    def get_recent_signals(self, user_id: str, limit: int = 50) -> list[dict]:
        _ensure_tables()
        conn = _connect()
        rows = conn.execute(
            "SELECT signal_id, user_id, signal_type, topic, source, created_at "
            "FROM profile_signals WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        conn.close()
        return [
            {
                "signal_id": r[0],
                "user_id": r[1],
                "signal_type": r[2],
                "topic": r[3],
                "source": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_model_config(self, user_id: str) -> dict:
        _ensure_tables()
        conn = _connect()
        row = conn.execute(
            "SELECT model_config FROM user_profile WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if row is None or row[0] is None:
            return {}
        return json.loads(row[0])

    def set_model_config(self, user_id: str, config: dict) -> None:
        _ensure_tables()
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO user_profile (user_id, model_config, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET model_config = excluded.model_config, updated_at = excluded.updated_at",
            (user_id, json.dumps(config), now),
        )
        conn.commit()
        conn.close()
