"""Scheduler store — owns scheduled_tasks table in the shared DB."""
import time
import uuid

from src.core.db import _connect


_migrated = False


def parse_interval(schedule: str) -> float:
    """Parse a schedule string like '4h' or '30m' into seconds."""
    value = int(schedule[:-1])
    unit = schedule[-1]
    if unit == "h":
        return value * 3600
    elif unit == "m":
        return value * 60
    else:
        raise ValueError(f"Unknown schedule unit: {unit}")


def _ensure_table() -> None:
    global _migrated
    if _migrated:
        return
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            task_id     TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            task_type   TEXT NOT NULL,
            schedule    TEXT NOT NULL,
            last_run_at REAL,
            next_run_at REAL NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user
        ON scheduled_tasks(user_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
        ON scheduled_tasks(next_run_at, enabled)
    """)
    conn.commit()
    conn.close()
    _migrated = True


class SchedulerStore:
    def create_task(self, user_id: str, task_type: str, schedule: str) -> dict:
        _ensure_table()
        task_id = str(uuid.uuid4())
        now = time.time()
        next_run_at = now + parse_interval(schedule)
        conn = _connect()
        conn.execute(
            "INSERT INTO scheduled_tasks (task_id, user_id, task_type, schedule, last_run_at, next_run_at, enabled) "
            "VALUES (?, ?, ?, ?, NULL, ?, 1)",
            (task_id, user_id, task_type, schedule, next_run_at),
        )
        conn.commit()
        conn.close()
        return {
            "task_id": task_id,
            "user_id": user_id,
            "task_type": task_type,
            "schedule": schedule,
            "last_run_at": None,
            "next_run_at": next_run_at,
            "enabled": True,
        }

    def get_user_tasks(self, user_id: str) -> list[dict]:
        _ensure_table()
        conn = _connect()
        rows = conn.execute(
            "SELECT task_id, user_id, task_type, schedule, last_run_at, next_run_at, enabled "
            "FROM scheduled_tasks WHERE user_id = ? ORDER BY next_run_at",
            (user_id,),
        ).fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]

    def get_overdue_tasks(self) -> list[dict]:
        _ensure_table()
        now = time.time()
        conn = _connect()
        rows = conn.execute(
            "SELECT task_id, user_id, task_type, schedule, last_run_at, next_run_at, enabled "
            "FROM scheduled_tasks WHERE next_run_at <= ? AND enabled = 1",
            (now,),
        ).fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]

    def mark_completed(self, task_id: str) -> None:
        _ensure_table()
        now = time.time()
        conn = _connect()
        row = conn.execute(
            "SELECT schedule FROM scheduled_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            conn.close()
            return
        schedule = row[0]
        next_run_at = now + parse_interval(schedule)
        conn.execute(
            "UPDATE scheduled_tasks SET last_run_at = ?, next_run_at = ? WHERE task_id = ?",
            (now, next_run_at, task_id),
        )
        conn.commit()
        conn.close()

    def update_task(
        self, task_id: str, user_id: str,
        schedule: str | None = None, enabled: bool | None = None,
    ) -> dict | None:
        _ensure_table()
        conn = _connect()
        row = conn.execute(
            "SELECT task_id, user_id, task_type, schedule, last_run_at, next_run_at, enabled "
            "FROM scheduled_tasks WHERE task_id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            conn.close()
            return None

        current = _row_to_dict(row)

        if schedule is not None:
            current["schedule"] = schedule
            current["next_run_at"] = time.time() + parse_interval(schedule)

        if enabled is not None:
            current["enabled"] = enabled

        conn.execute(
            "UPDATE scheduled_tasks SET schedule = ?, next_run_at = ?, enabled = ? "
            "WHERE task_id = ? AND user_id = ?",
            (current["schedule"], current["next_run_at"], int(current["enabled"]), task_id, user_id),
        )
        conn.commit()
        conn.close()
        return current

    def delete_task(self, task_id: str, user_id: str) -> bool:
        _ensure_table()
        conn = _connect()
        cursor = conn.execute(
            "DELETE FROM scheduled_tasks WHERE task_id = ? AND user_id = ?",
            (task_id, user_id),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted


def _row_to_dict(row: tuple) -> dict:
    return {
        "task_id": row[0],
        "user_id": row[1],
        "task_type": row[2],
        "schedule": row[3],
        "last_run_at": row[4],
        "next_run_at": row[5],
        "enabled": bool(row[6]),
    }
