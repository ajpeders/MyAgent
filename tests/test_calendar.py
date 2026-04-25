"""Tests for the calendar service."""
import pytest

from src.services.calendar.errors import EventNotFoundError
from src.services.calendar.service import CalendarService
from src.services.calendar.store import CalendarStore


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    from pathlib import Path
    db_path = Path(tmp_path / "test.db")
    monkeypatch.setattr("src.core.db.DB_PATH", db_path)
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.services.auth.store.DB_PATH", db_path)
    monkeypatch.setattr("src.services.auth.store._schema_initialized", False)
    monkeypatch.setattr("src.services.calendar.store._migrated", False)
    # Insert synthetic users directly for FK constraints in store-level tests
    from src.core.db import _connect
    import time as _time
    conn = _connect()
    for uid in ("u1", "u2"):
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, email, password_hash, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
            (uid, f"cal-{uid}@test.com", _time.time(), _time.time()),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def service():
    return CalendarService()


@pytest.fixture
def store():
    return CalendarStore()


class TestCalendarStore:
    def test_create_event(self, store):
        event = store.create_event("u1", "Standup", "2026-04-25", time_="09:00")
        assert event["title"] == "Standup"
        assert event["date"] == "2026-04-25"
        assert event["time"] == "09:00"
        assert event["user_id"] == "u1"
        assert event["id"]

    def test_get_events_in_range(self, store):
        store.create_event("u1", "Apr 1", "2026-04-01")
        store.create_event("u1", "Apr 15", "2026-04-15")
        store.create_event("u1", "May 1", "2026-05-01")

        events = store.get_events_in_range("u1", "2026-04-01", "2026-04-30")
        assert len(events) == 2
        assert events[0]["title"] == "Apr 1"
        assert events[1]["title"] == "Apr 15"

    def test_get_events_scoped_to_user(self, store):
        store.create_event("u1", "Mine", "2026-04-25")
        store.create_event("u2", "Theirs", "2026-04-25")

        events = store.get_events_in_range("u1", "2026-04-01", "2026-04-30")
        assert len(events) == 1
        assert events[0]["title"] == "Mine"

    def test_delete_event(self, store):
        event = store.create_event("u1", "Delete me", "2026-04-25")
        assert store.delete_event(event["id"], "u1") is True
        assert store.get_event(event["id"], "u1") is None

    def test_delete_event_wrong_user(self, store):
        event = store.create_event("u1", "Not yours", "2026-04-25")
        assert store.delete_event(event["id"], "u2") is False

    def test_delete_nonexistent(self, store):
        assert store.delete_event("no-such-id", "u1") is False

    def test_events_sorted_by_date_and_time(self, store):
        store.create_event("u1", "Late", "2026-04-25", time_="17:00")
        store.create_event("u1", "Early", "2026-04-25", time_="09:00")
        store.create_event("u1", "Yesterday", "2026-04-24")

        events = store.get_events_in_range("u1", "2026-04-24", "2026-04-25")
        assert [e["title"] for e in events] == ["Yesterday", "Early", "Late"]


class TestCalendarService:
    def test_create_and_list(self, service):
        service.create_event("u1", "Meeting", "2026-04-25", time="14:00", description="Weekly sync")
        events = service.get_events("u1", "2026-04-25", "2026-04-25")
        assert len(events) == 1
        assert events[0].title == "Meeting"
        assert events[0].time == "14:00"
        assert events[0].description == "Weekly sync"

    def test_delete_raises_on_not_found(self, service):
        with pytest.raises(EventNotFoundError):
            service.delete_event("nonexistent", "u1")

    def test_create_minimal_event(self, service):
        event = service.create_event("u1", "Reminder", "2026-04-25")
        assert event.title == "Reminder"
        assert event.time is None
        assert event.description is None
