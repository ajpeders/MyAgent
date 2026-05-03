import json
import pytest
from unittest.mock import patch
from src.services.news.curator import NewsCurator


@pytest.fixture
def curator(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("src.services.profile.store._migrated", False)
    monkeypatch.setattr("src.services.news.store._migrated", False)
    from src.core.db import _connect
    conn = _connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "user_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, "
        "password_hash TEXT, encrypted_imap_creds BLOB, "
        "mail_model TEXT, mail_preferences TEXT, search_provider TEXT, "
        "is_admin INTEGER NOT NULL DEFAULT 0, "
        "created_at REAL NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO users (user_id, email, created_at, updated_at) "
        "VALUES ('u1', 'test@test.com', 0, 0)"
    )
    conn.commit()
    conn.close()
    return NewsCurator()


@pytest.mark.asyncio
async def test_curate_returns_zero_when_no_articles(curator):
    from src.services.profile.service import ProfileService
    ProfileService().set_interests("u1", ["AI"])
    result = await curator.curate("u1")
    assert result == 0


@pytest.mark.asyncio
async def test_curate_scores_and_saves_picks(curator):
    from src.services.news.store import NewsStore
    from src.services.profile.service import ProfileService
    ProfileService().set_interests("u1", ["AI"])
    store = NewsStore()
    src = store.create_source("u1", "Test", "Tech", "http://test.com/rss")
    store.upsert_articles("u1", src["id"], [
        {"title": "AI breakthrough", "topic": "Tech", "url": "http://test.com/1", "published_at": "2026-05-01", "summary": "Big AI news"}
    ])
    uncurated = store.get_uncurated_articles("u1")
    real_id = uncurated[0]["id"]

    llm_response = json.dumps({"results": [
        {"article_id": real_id, "score": 0.9, "summary": "Major AI advance", "reason": "Matches AI interest"}
    ]})

    with patch("src.services.news.curator.default_adapter") as mock_adapter:
        mock_adapter.complete_sync.return_value = llm_response
        result = await curator.curate("u1")

    assert result == 1
    curated = store.list_curated("u1")
    assert len(curated) == 1
    assert curated[0]["summary"] == "Major AI advance"


@pytest.mark.asyncio
async def test_curate_skips_low_scores(curator):
    from src.services.news.store import NewsStore
    from src.services.profile.service import ProfileService
    ProfileService().set_interests("u1", ["AI"])
    store = NewsStore()
    src = store.create_source("u1", "Test", "Tech", "http://test.com/rss")
    store.upsert_articles("u1", src["id"], [
        {"title": "Boring", "topic": "Tech", "url": "http://test.com/2", "published_at": "2026-05-01", "summary": "Meh"}
    ])
    uncurated = store.get_uncurated_articles("u1")

    llm_response = json.dumps({"results": [
        {"article_id": uncurated[0]["id"], "score": 0.2, "summary": "Not relevant", "reason": "Low match"}
    ]})

    with patch("src.services.news.curator.default_adapter") as mock_adapter:
        mock_adapter.complete_sync.return_value = llm_response
        result = await curator.curate("u1")

    assert result == 0
