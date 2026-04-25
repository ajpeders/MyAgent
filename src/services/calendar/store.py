"""Calendar store — owns calendar_events table in the shared DB."""
import time
import uuid

from src.core.db import _connect


_migrated = False


def _ensure_table() -> None:
    global _migrated
    if _migrated:
        return
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            event_id    TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            title       TEXT NOT NULL,
            date        TEXT NOT NULL,
            time        TEXT,
            description TEXT,
            created_at  REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_calendar_user_date
        ON calendar_events(user_id, date)
    """)
    conn.commit()
    conn.close()
    _migrated = True


class CalendarStore:
    def create_event(
        self, user_id: str, title: str, date: str,
        time_: str | None = None, description: str | None = None,
    ) -> dict:
        _ensure_table()
        event_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO calendar_events (event_id, user_id, title, date, time, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, user_id, title, date, time_, description, now),
        )
        conn.commit()
        conn.close()
        return {
            "id": event_id,
            "user_id": user_id,
            "title": title,
            "date": date,
            "time": time_,
            "description": description,
            "created_at": now,
        }

    def get_events_in_range(self, user_id: str, start: str, end: str) -> list[dict]:
        _ensure_table()
        conn = _connect()
        rows = conn.execute(
            "SELECT event_id, user_id, title, date, time, description, created_at "
            "FROM calendar_events WHERE user_id = ? AND date >= ? AND date <= ? "
            "ORDER BY date, time",
            (user_id, start, end),
        ).fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]

    def get_event(self, event_id: str, user_id: str) -> dict | None:
        _ensure_table()
        conn = _connect()
        row = conn.execute(
            "SELECT event_id, user_id, title, date, time, description, created_at "
            "FROM calendar_events WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        ).fetchone()
        conn.close()
        return _row_to_dict(row) if row else None

    def delete_event(self, event_id: str, user_id: str) -> bool:
        _ensure_table()
        conn = _connect()
        cursor = conn.execute(
            "DELETE FROM calendar_events WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted


def _row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "title": row[2],
        "date": row[3],
        "time": row[4],
        "description": row[5],
        "created_at": row[6],
    }
