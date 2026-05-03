"""Tests for curated feed and rating API endpoints."""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from src.gateway.__main__ import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("src.services.news.store._migrated", False)
    monkeypatch.setattr("src.services.profile.store._migrated", False)
    from src.core.db import _connect
    conn = _connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
        password_hash TEXT, encrypted_imap_creds BLOB,
        mail_model TEXT, mail_preferences TEXT, search_provider TEXT,
        is_admin INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""")
    conn.execute("INSERT INTO users VALUES ('u1', 'test@test.com', NULL, NULL, NULL, NULL, NULL, 0, 0, 0)")
    conn.commit()
    conn.close()
    # Ensure news tables exist and insert test data for FK constraints
    import src.services.news.store as _ns
    _ns._ensure_tables()
    conn = _connect()
    conn.execute(
        "INSERT INTO news_sources (source_id, user_id, label, topic, feed_url, enabled, created_at) "
        "VALUES ('src-1', 'u1', 'Test Source', 'Tech', 'http://example.com/feed', 1, 0)"
    )
    conn.execute(
        "INSERT INTO news_articles (article_id, source_id, user_id, title, topic, url, published_at, summary, fetched_at) "
        "VALUES ('art-1', 'src-1', 'u1', 'Test Article', 'Tech', 'http://example.com/1', '2026-01-01', NULL, 0)"
    )
    conn.execute(
        "INSERT INTO curated_articles (curated_id, user_id, article_id, summary, relevance_score, reason, created_at) "
        "VALUES ('cur-1', 'u1', 'art-1', 'Test summary', 0.9, 'relevant', 0)"
    )
    conn.commit()
    conn.close()
    return TestClient(app)


@pytest.fixture
def auth_headers():
    from src.core.jwt import create_session_token
    token = create_session_token("u1", enc_key="", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    from src.core.jwt import create_session_token
    token = create_session_token("u1", enc_key="", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


def test_get_curated(client, auth_headers):
    resp = client.get("/api/news/curated", headers=auth_headers)
    assert resp.status_code == 200
    articles = resp.json()["articles"]
    assert isinstance(articles, list)
    assert len(articles) == 1
    assert articles[0]["curated_id"] == "cur-1"


def test_rate_curated(client, auth_headers):
    resp = client.post("/api/news/curated/cur-1/rate", json={"rating": 1}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_rate_source(client, auth_headers):
    resp = client.post("/api/news/sources/src-1/rate", json={"rating": -1}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_curate_requires_admin(client, auth_headers):
    resp = client.post("/api/news/curate", headers=auth_headers)
    assert resp.status_code == 403


def test_curate_admin_ok(client, admin_headers):
    with patch("src.gateway.routes.news.NewsCurator") as MockCurator:
        mock_instance = MockCurator.return_value
        mock_instance.curate = AsyncMock(return_value=5)
        resp = client.post("/api/news/curate", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["curated"] == 5
