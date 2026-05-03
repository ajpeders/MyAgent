"""Tests for the scheduler store and service."""
import time

import pytest

from src.services.scheduler.store import SchedulerStore, parse_interval
from src.services.scheduler.service import SchedulerService


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    from pathlib import Path
    db_path = Path(tmp_path / "test.db")
    monkeypatch.setattr("src.core.db.DB_PATH", db_path)
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.services.scheduler.store._migrated", False)
    from src.core.db import _connect
    import time as _time
    conn = _connect()
    for uid in ("u1", "u2"):
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, email, password_hash, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
            (uid, f"sched-{uid}@test.com", _time.time(), _time.time()),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def store():
    return SchedulerStore()


@pytest.fixture
def service():
    return SchedulerService()


class TestParseInterval:
    def test_hours(self):
        assert parse_interval("4h") == 4 * 3600

    def test_minutes(self):
        assert parse_interval("30m") == 30 * 60

    def test_unknown_unit(self):
        with pytest.raises(ValueError, match="Unknown schedule unit"):
            parse_interval("5d")


class TestSchedulerStore:
    def test_create_and_list(self, store):
        task = store.create_task("u1", "news_curation", "4h")
        assert task["task_type"] == "news_curation"
        assert task["schedule"] == "4h"
        assert task["enabled"] is True
        assert task["last_run_at"] is None
        assert task["next_run_at"] > time.time() - 1

        tasks = store.get_user_tasks("u1")
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == task["task_id"]

    def test_user_scoping(self, store):
        store.create_task("u1", "news_curation", "4h")
        store.create_task("u2", "news_curation", "2h")
        assert len(store.get_user_tasks("u1")) == 1
        assert len(store.get_user_tasks("u2")) == 1

    def test_overdue_detection(self, store, monkeypatch):
        task = store.create_task("u1", "news_curation", "1m")
        # Force next_run_at to the past
        from src.core.db import _connect
        conn = _connect()
        conn.execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE task_id = ?",
            (time.time() - 100, task["task_id"]),
        )
        conn.commit()
        conn.close()

        overdue = store.get_overdue_tasks()
        assert len(overdue) == 1
        assert overdue[0]["task_id"] == task["task_id"]

    def test_overdue_excludes_disabled(self, store):
        task = store.create_task("u1", "news_curation", "1m")
        from src.core.db import _connect
        conn = _connect()
        conn.execute(
            "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 0 WHERE task_id = ?",
            (time.time() - 100, task["task_id"]),
        )
        conn.commit()
        conn.close()

        overdue = store.get_overdue_tasks()
        assert len(overdue) == 0

    def test_mark_completed_recomputes(self, store):
        task = store.create_task("u1", "news_curation", "2h")
        before = time.time()
        store.mark_completed(task["task_id"])
        after = time.time()

        tasks = store.get_user_tasks("u1")
        assert len(tasks) == 1
        t = tasks[0]
        assert t["last_run_at"] is not None
        assert before <= t["last_run_at"] <= after
        # next_run_at should be ~2h from now
        assert t["next_run_at"] >= before + 2 * 3600

    def test_update_schedule(self, store):
        task = store.create_task("u1", "news_curation", "4h")
        updated = store.update_task(task["task_id"], "u1", schedule="1h")
        assert updated is not None
        assert updated["schedule"] == "1h"
        # next_run_at recomputed to ~1h from now
        assert updated["next_run_at"] < task["next_run_at"]

    def test_update_enabled(self, store):
        task = store.create_task("u1", "news_curation", "4h")
        updated = store.update_task(task["task_id"], "u1", enabled=False)
        assert updated is not None
        assert updated["enabled"] is False

    def test_update_wrong_user(self, store):
        task = store.create_task("u1", "news_curation", "4h")
        result = store.update_task(task["task_id"], "u2", schedule="1h")
        assert result is None

    def test_delete_task(self, store):
        task = store.create_task("u1", "news_curation", "4h")
        assert store.delete_task(task["task_id"], "u1") is True
        assert store.get_user_tasks("u1") == []

    def test_delete_wrong_user(self, store):
        task = store.create_task("u1", "news_curation", "4h")
        assert store.delete_task(task["task_id"], "u2") is False


class TestSchedulerService:
    def test_create_and_list(self, service):
        task = service.create_task("u1", "news_curation", "4h")
        assert task.task_type == "news_curation"
        assert task.schedule == "4h"
        assert task.enabled is True

        tasks = service.get_user_tasks("u1")
        assert len(tasks) == 1
        assert tasks[0].task_id == task.task_id

    def test_update_returns_model(self, service):
        task = service.create_task("u1", "news_curation", "4h")
        updated = service.update_task(task.task_id, "u1", schedule="2h")
        assert updated is not None
        assert updated.schedule == "2h"

    def test_update_nonexistent_returns_none(self, service):
        result = service.update_task("no-such-id", "u1", schedule="1h")
        assert result is None
