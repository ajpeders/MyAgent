import pytest
from src.services.profile.store import ProfileStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.core.db._schema_initialized_path", None)
    monkeypatch.setattr("src.services.profile.store._migrated", False)
    from src.core.db import _connect
    conn = _connect()
    conn.execute("INSERT INTO users VALUES ('u1', 'test@test.com', NULL, NULL, NULL, NULL, NULL, 0, 0, 0)")
    conn.commit()
    conn.close()
    return ProfileStore()


def test_get_interests_returns_empty_for_new_user(store):
    assert store.get_interests("u1") == []


def test_set_and_get_interests(store):
    store.set_interests("u1", ["AI", "hip hop", "gaming"])
    assert store.get_interests("u1") == ["AI", "hip hop", "gaming"]


def test_set_interests_overwrites(store):
    store.set_interests("u1", ["AI"])
    store.set_interests("u1", ["gaming"])
    assert store.get_interests("u1") == ["gaming"]


def test_log_and_get_signals(store):
    store.log_signal("u1", "article_click", "AI", "Ars Technica")
    store.log_signal("u1", "topic_browse", "Gaming", "news_page")
    signals = store.get_recent_signals("u1", limit=10)
    assert len(signals) == 2
    assert signals[0]["topic"] == "Gaming"  # most recent first


def test_model_config_defaults_to_empty(store):
    assert store.get_model_config("u1") == {}


def test_set_and_get_model_config(store):
    store.set_model_config("u1", {"news_curation": "qwen3:32b", "core_chat": "llama3.1:8b"})
    config = store.get_model_config("u1")
    assert config["news_curation"] == "qwen3:32b"
    assert config["core_chat"] == "llama3.1:8b"
