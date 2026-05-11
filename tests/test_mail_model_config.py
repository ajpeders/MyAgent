"""Tests for user-configurable mail model settings."""
from unittest.mock import MagicMock, patch

from src.gateway.session import SessionState


class DummyRequest:
    def __init__(self, headers=None, query_params=None, body_json: str = ""):
        self._headers = headers or {}
        self._query_params = query_params or {}
        self._body = body_json

    @property
    def headers(self):
        return MagicMock(get=lambda key, default=None: self._headers.get(key, default))

    @property
    def query_params(self):
        return MagicMock(get=lambda key, default=None: self._query_params.get(key, default))

    async def body(self):
        return self._body.encode()


@patch("src.gateway.routes.auth._discover_mail_models", return_value=["qwen3:8b", "llama3.1:8b"])
def test_get_mail_config_returns_current_model(mock_models, tmp_path, monkeypatch):
    from pathlib import Path
    import src.core.db
    from src.services.auth.store import UserStore
    from src.gateway.routes.auth import get_mail_config

    monkeypatch.setattr("src.core.db.DB_PATH", Path(tmp_path / "test.db"))
    src.core.db._schema_initialized = False
    store = UserStore()
    user_id = store.create_user("model@test.com", "pw")
    store.update_mail_model(user_id, "qwen3:8b")

    import asyncio

    async def run():
        with patch("src.gateway.routes.auth.jwt_required", return_value={"user_id": user_id}):
            return await get_mail_config(DummyRequest())

    data = asyncio.run(run())
    assert data.body
    assert b'"mail_preferences":""' in data.body


@patch("src.gateway.routes.auth.jwt_required", return_value={"user_id": "u1"})
@patch("src.gateway.routes.auth._discover_mail_models", return_value=["qwen3:8b", "llama3.1:8b"])
def test_update_mail_config_persists_model(mock_models, _jwt, tmp_path, monkeypatch):
    from pathlib import Path
    import asyncio
    import json
    import src.core.db
    from src.services.auth.store import UserStore
    from src.gateway.routes.auth import update_mail_config

    monkeypatch.setattr("src.core.db.DB_PATH", Path(tmp_path / "test.db"))
    src.core.db._schema_initialized = False
    store = UserStore()
    user_id = store.create_user("model@test.com", "pw")

    async def run():
        with patch("src.gateway.routes.auth.jwt_required", return_value={"user_id": user_id}):
            response = await update_mail_config(DummyRequest(body_json=json.dumps({"mail_model": "llama3.1:8b", "mail_preferences": "prefer reply"})))
            return response

    response = asyncio.run(run())
    assert store.get_user_by_id(user_id)["mail_model"] == "llama3.1:8b"
    assert store.get_user_by_id(user_id)["mail_preferences"] == "prefer reply"
    assert response.status_code == 200
