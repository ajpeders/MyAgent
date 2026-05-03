"""Tests for the scheduler runner."""
import asyncio
import time

import pytest

from src.services.scheduler.runner import TASK_HANDLERS, scheduler_loop
from src.services.scheduler.store import SchedulerStore


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    from pathlib import Path
    db_path = Path(tmp_path / "test.db")
    monkeypatch.setattr("src.core.db.DB_PATH", db_path)
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.services.scheduler.store._migrated", False)
    monkeypatch.setattr("src.services.scheduler.runner._store", SchedulerStore())
    from src.core.db import _connect
    import time as _time
    conn = _connect()
    for uid in ("u1",):
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, email, password_hash, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
            (uid, f"runner-{uid}@test.com", _time.time(), _time.time()),
        )
    conn.commit()
    conn.close()


class TestTaskHandlers:
    def test_news_curation_handler_exists(self):
        assert "news_curation" in TASK_HANDLERS

    def test_handler_is_callable(self):
        handler = TASK_HANDLERS["news_curation"]
        assert callable(handler)


class TestSchedulerLoop:
    @pytest.mark.asyncio
    async def test_dispatches_overdue_task(self, monkeypatch):
        """Verify the runner calls the handler for an overdue task and marks it completed."""
        store = SchedulerStore()
        task = store.create_task("u1", "news_curation", "1m")

        # Force task to be overdue
        from src.core.db import _connect
        conn = _connect()
        conn.execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE task_id = ?",
            (time.time() - 100, task["task_id"]),
        )
        conn.commit()
        conn.close()

        # Track calls
        calls = []

        async def fake_curate(user_id):
            calls.append(user_id)
            return 5

        monkeypatch.setitem(TASK_HANDLERS, "news_curation", fake_curate)

        # Run one iteration then cancel
        async def run_once():
            loop_task = asyncio.create_task(scheduler_loop(poll_interval=0.01))
            await asyncio.sleep(0.05)
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        await run_once()

        assert "u1" in calls

        # Verify mark_completed was called (next_run_at moved forward)
        tasks = store.get_user_tasks("u1")
        assert len(tasks) == 1
        assert tasks[0]["last_run_at"] is not None
        assert tasks[0]["next_run_at"] > time.time()

    @pytest.mark.asyncio
    async def test_handler_exception_doesnt_crash_loop(self, monkeypatch):
        """If a handler raises, the loop should continue without crashing."""
        store = SchedulerStore()
        task = store.create_task("u1", "news_curation", "1m")

        from src.core.db import _connect
        conn = _connect()
        conn.execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE task_id = ?",
            (time.time() - 100, task["task_id"]),
        )
        conn.commit()
        conn.close()

        async def failing_handler(user_id):
            raise RuntimeError("boom")

        monkeypatch.setitem(TASK_HANDLERS, "news_curation", failing_handler)

        # Should not raise
        loop_task = asyncio.create_task(scheduler_loop(poll_interval=0.01))
        await asyncio.sleep(0.05)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Task should NOT be marked completed since handler failed
        tasks = store.get_user_tasks("u1")
        assert tasks[0]["last_run_at"] is None
