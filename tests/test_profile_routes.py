import pytest
from fastapi.testclient import TestClient
from src.gateway.__main__ import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
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
    return TestClient(app)


@pytest.fixture
def auth_headers():
    from src.core.jwt import create_session_token
    token = create_session_token("u1", enc_key="", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


def test_get_profile_empty(client, auth_headers):
    resp = client.get("/api/profile", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["interests"] == []
    assert data["model_config"] == {}


def test_set_interests(client, auth_headers):
    resp = client.put("/api/profile/interests", json={"interests": ["AI", "gaming"]}, headers=auth_headers)
    assert resp.status_code == 200
    resp = client.get("/api/profile", headers=auth_headers)
    assert resp.json()["interests"] == ["AI", "gaming"]


def test_set_model_config(client, auth_headers):
    resp = client.put("/api/profile/models", json={"config": {"news_curation": "qwen3:32b"}}, headers=auth_headers)
    assert resp.status_code == 200
    resp = client.get("/api/profile", headers=auth_headers)
    assert resp.json()["model_config"]["news_curation"] == "qwen3:32b"


def test_log_signal(client, auth_headers):
    resp = client.post("/api/profile/signal", json={"signal_type": "article_click", "topic": "AI", "source": "news"}, headers=auth_headers)
    assert resp.status_code == 200
