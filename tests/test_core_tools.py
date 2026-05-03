"""Tests for core agent tool definitions and handlers."""
import datetime
import pytest

from src.core.tools.registry import (
    CORE_TOOLS, SEARCH_NEWS, GET_CURATED, GET_CALENDAR,
    GET_MAIL_SUMMARY, GET_MEMORIES, GET_PROFILE, CREATE_CALENDAR_EVENT,
    ANSWER, REMEMBER, DONE,
)
from src.core.executor import ToolContext


# ── Tool definitions ─────────────────────────────────────────────────────────

class TestCoreToolDefs:
    def test_core_tools_has_10_items(self):
        assert len(CORE_TOOLS) == 10

    def test_core_tools_names(self):
        names = [t.name for t in CORE_TOOLS]
        assert names == [
            "search_news", "get_curated", "get_calendar", "get_mail_summary",
            "get_memories", "get_profile", "create_calendar_event",
            "answer", "remember", "done",
        ]

    def test_search_news_has_required_query(self):
        query_param = next(p for p in SEARCH_NEWS.params if p.name == "query")
        assert query_param.required is True
        assert query_param.type == "string"

    def test_get_calendar_default_days(self):
        days_param = next(p for p in GET_CALENDAR.params if p.name == "days")
        assert days_param.default == 3

    def test_create_calendar_event_required_params(self):
        required = [p.name for p in CREATE_CALENDAR_EVENT.params if p.required]
        assert "title" in required
        assert "date" in required

    def test_get_profile_has_no_params(self):
        assert GET_PROFILE.params == []


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    from pathlib import Path
    db_path = Path(tmp_path / "test.db")
    monkeypatch.setattr("src.core.db.DB_PATH", db_path)
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.services.calendar.store._migrated", False)
    monkeypatch.setattr("src.services.news.store._migrated", False)

    from src.core.db import _connect
    import time as _time
    conn = _connect()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, email, password_hash, created_at, updated_at) "
        "VALUES (?, ?, '', ?, ?)",
        ("u1", "core@test.com", _time.time(), _time.time()),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def ctx():
    return ToolContext(session_id="test", user_id="u1")


# ── Handler tests ────────────────────────────────────────────────────────────

class TestSearchNewsHandler:
    @pytest.mark.asyncio
    async def test_returns_articles_matching_query(self, ctx):
        from src.core.executor import _tool_search_news
        from src.services.news.store import NewsStore

        store = NewsStore()
        src = store.create_source("u1", "Test Source", "tech", "http://example.com/feed")
        store.upsert_articles("u1", src["id"], [
            {"title": "Python 4 Released", "topic": "tech", "url": "http://a.com/1", "published_at": "2026-05-01"},
            {"title": "Rust News Today", "topic": "tech", "url": "http://a.com/2", "published_at": "2026-05-01"},
        ])

        result = await _tool_search_news({"query": "Python"}, ctx)
        assert "Python 4 Released" in result
        assert "Rust News Today" not in result

    @pytest.mark.asyncio
    async def test_returns_no_articles_message(self, ctx):
        from src.core.executor import _tool_search_news

        result = await _tool_search_news({"query": "nonexistent"}, ctx)
        assert "No news articles found" in result


class TestGetCuratedHandler:
    @pytest.mark.asyncio
    async def test_returns_curated_articles(self, ctx):
        from src.core.executor import _tool_get_curated
        from src.services.news.store import NewsStore

        store = NewsStore()
        src = store.create_source("u1", "Src", "tech", "http://example.com/feed")
        store.upsert_articles("u1", src["id"], [
            {"title": "Big Story", "topic": "tech", "url": "http://a.com/1", "published_at": "2026-05-01"},
        ])
        articles = store.list_articles("u1")
        store.upsert_curated("u1", articles[0]["id"], "Summary here", 0.9, "Relevant")

        result = await _tool_get_curated({"count": 5}, ctx)
        assert "Big Story" in result

    @pytest.mark.asyncio
    async def test_returns_empty_message(self, ctx):
        from src.core.executor import _tool_get_curated

        result = await _tool_get_curated({}, ctx)
        assert "No curated articles" in result


class TestGetCalendarHandler:
    @pytest.mark.asyncio
    async def test_returns_events(self, ctx):
        from src.core.executor import _tool_get_calendar
        from src.services.calendar.service import CalendarService

        today = datetime.date.today().isoformat()
        CalendarService().create_event("u1", "Standup", today, time="09:00")

        result = await _tool_get_calendar({"days": 1}, ctx)
        assert "Standup" in result
        assert "09:00" in result

    @pytest.mark.asyncio
    async def test_returns_no_events_message(self, ctx):
        from src.core.executor import _tool_get_calendar

        result = await _tool_get_calendar({"days": 1}, ctx)
        assert "No upcoming events" in result


class TestGetMailSummaryHandler:
    @pytest.mark.asyncio
    async def test_returns_degraded_message(self, ctx):
        from src.core.executor import _tool_get_mail_summary

        result = await _tool_get_mail_summary({}, ctx)
        assert "not available" in result


class TestGetMemoriesHandler:
    @pytest.mark.asyncio
    async def test_calls_recall(self, ctx, monkeypatch):
        from src.core import executor

        async def _handler(params, c):
            # Inline to avoid import issues; mock at the recall level
            return await executor._tool_get_memories(params, c)

        monkeypatch.setattr(
            "src.core.memory.recall",
            lambda q, uid, top_k=5: [{"content": "Likes hiking", "score": 0.95}],
        )
        result = await _handler({"query": "hobbies"}, ctx)
        assert "Likes hiking" in result
        assert "95%" in result

    @pytest.mark.asyncio
    async def test_no_memories(self, ctx, monkeypatch):
        from src.core import executor

        monkeypatch.setattr("src.core.memory.recall", lambda q, uid, top_k=5: [])
        result = await executor._tool_get_memories({"query": "nothing"}, ctx)
        assert "No relevant memories" in result


class TestGetProfileHandler:
    @pytest.mark.asyncio
    async def test_returns_profile_data(self, ctx, monkeypatch):
        from src.core.executor import _tool_get_profile
        from src.services.profile.models import ContextSnapshot

        fake_snapshot = ContextSnapshot(
            user_id="u1",
            interests=["tech", "hiking"],
            recent_signals=[],
            calendar_today=[],
            calendar_upcoming=[],
            mail_subjects=[],
            memories=[],
        )
        monkeypatch.setattr(
            "src.services.profile.service.ProfileService.context_snapshot",
            lambda self, uid: fake_snapshot,
        )
        result = await _tool_get_profile({}, ctx)
        assert "tech" in result
        assert "hiking" in result

    @pytest.mark.asyncio
    async def test_handles_exception(self, ctx, monkeypatch):
        from src.core.executor import _tool_get_profile

        def _boom(self, uid):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.services.profile.service.ProfileService.context_snapshot", _boom,
        )
        result = await _tool_get_profile({}, ctx)
        assert "unavailable" in result.lower()


class TestCreateCalendarEventHandler:
    @pytest.mark.asyncio
    async def test_creates_event(self, ctx):
        from src.core.executor import _tool_create_calendar_event

        result = await _tool_create_calendar_event(
            {"title": "Lunch", "date": "2026-05-10", "time": "12:30"}, ctx
        )
        assert "Lunch" in result
        assert "2026-05-10" in result
        assert "12:30" in result

    @pytest.mark.asyncio
    async def test_creates_event_minimal(self, ctx):
        from src.core.executor import _tool_create_calendar_event

        result = await _tool_create_calendar_event(
            {"title": "Reminder", "date": "2026-05-10"}, ctx
        )
        assert "Reminder" in result
