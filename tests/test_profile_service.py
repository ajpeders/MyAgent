import pytest
from src.services.profile.service import ProfileService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.core.db._schema_initialized_path", None)
    monkeypatch.setattr("src.services.profile.store._migrated", False)
    from src.core.db import _connect
    conn = _connect()  # triggers _init_schema with full users table
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, email, created_at, updated_at) VALUES ('u1', 'test@test.com', 0, 0)"
    )
    conn.commit()
    conn.close()
    return ProfileService()


def test_set_and_get_interests(service):
    service.set_interests("u1", ["AI", "gaming"])
    assert service.get_interests("u1") == ["AI", "gaming"]


def test_get_model_falls_back_to_default(service):
    model = service.get_model("u1", "news_curation")
    assert model  # returns DEFAULT_MODEL, not empty


def test_get_model_uses_user_config(service):
    service.set_model_config("u1", {"news_curation": "qwen3:32b"})
    assert service.get_model("u1", "news_curation") == "qwen3:32b"
    assert service.get_model("u1", "core_chat") != "qwen3:32b"


def test_context_snapshot_returns_all_fields(service):
    service.set_interests("u1", ["AI"])
    service.log_signal("u1", "article_click", "AI", "Ars Technica")
    snapshot = service.context_snapshot("u1")
    assert snapshot.user_id == "u1"
    assert snapshot.interests == ["AI"]
    assert len(snapshot.recent_signals) == 1
    assert isinstance(snapshot.calendar_today, list)
    assert isinstance(snapshot.mail_subjects, list)
    assert isinstance(snapshot.memories, list)
