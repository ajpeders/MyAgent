"""Tests for per-user device tokens (used by iPhone Shortcut, etc.)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    import src.core.db
    src.core.db._schema_initialized = False


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-for-device-token-tests!")
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-for-device-token-tests!")


@pytest.fixture
def auth_service():
    from src.services.auth.service import AuthService
    return AuthService()


@pytest.fixture
def user(auth_service):
    return auth_service.register("user@test.com", "pw").user_id


@pytest.fixture
def client():
    from src.gateway.__main__ import app
    return TestClient(app)


@pytest.fixture
def headers_for(user):
    from src.core.jwt import create_session_token
    token = create_session_token(user, enc_key="", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


class TestServiceLayer:
    def test_generate_returns_plaintext_with_prefix(self, auth_service, user):
        result = auth_service.generate_device_token(user)
        assert result["token"].startswith("whsk_")
        assert len(result["token"]) > 20
        assert result["last4"] == result["token"][-4:]
        assert isinstance(result["created_at"], float)

    def test_generate_persists_hashed_not_plaintext(self, auth_service, user):
        import hashlib
        result = auth_service.generate_device_token(user)
        from src.core.db import _connect
        conn = _connect()
        row = conn.execute(
            "SELECT token_hash FROM device_tokens WHERE user_id = ?", (user,)
        ).fetchone()
        conn.close()
        stored_hash = row[0]
        assert stored_hash != result["token"]
        assert stored_hash == hashlib.sha256(result["token"].encode()).hexdigest()

    def test_generate_replaces_existing_token(self, auth_service, user):
        first = auth_service.generate_device_token(user)
        second = auth_service.generate_device_token(user)
        assert first["token"] != second["token"]
        assert auth_service.verify_device_token(first["token"]) is None
        assert auth_service.verify_device_token(second["token"]) == user

    def test_verify_returns_user_for_valid_token(self, auth_service, user):
        result = auth_service.generate_device_token(user)
        assert auth_service.verify_device_token(result["token"]) == user

    def test_verify_returns_none_for_unknown_token(self, auth_service):
        assert auth_service.verify_device_token("whsk_does_not_exist") is None

    def test_verify_rejects_missing_prefix(self, auth_service, user):
        result = auth_service.generate_device_token(user)
        bare = result["token"][len("whsk_"):]
        assert auth_service.verify_device_token(bare) is None

    def test_verify_rejects_empty_token(self, auth_service):
        assert auth_service.verify_device_token("") is None

    def test_verify_updates_last_used(self, auth_service, user):
        result = auth_service.generate_device_token(user)
        before = auth_service.get_device_token_meta(user)
        assert before["last_used_at"] is None
        auth_service.verify_device_token(result["token"])
        after = auth_service.get_device_token_meta(user)
        assert after["last_used_at"] is not None

    def test_meta_returns_none_when_no_token(self, auth_service, user):
        assert auth_service.get_device_token_meta(user) is None

    def test_meta_returns_metadata_only(self, auth_service, user):
        result = auth_service.generate_device_token(user)
        meta = auth_service.get_device_token_meta(user)
        assert meta["last4"] == result["last4"]
        assert meta["created_at"] == result["created_at"]
        assert "token" not in meta

    def test_revoke_deletes_token(self, auth_service, user):
        result = auth_service.generate_device_token(user)
        deleted = auth_service.revoke_device_token(user)
        assert deleted is True
        assert auth_service.verify_device_token(result["token"]) is None
        assert auth_service.get_device_token_meta(user) is None

    def test_revoke_returns_false_when_no_token(self, auth_service, user):
        assert auth_service.revoke_device_token(user) is False

    def test_generate_raises_for_unknown_user(self, auth_service):
        from src.services.auth.errors import UserNotFoundError
        with pytest.raises(UserNotFoundError):
            auth_service.generate_device_token("not-a-user")


class TestRoutes:
    def test_post_requires_jwt(self, client):
        r = client.post("/api/auth/device-token")
        assert r.status_code == 401

    def test_post_creates_token(self, client, headers_for):
        r = client.post("/api/auth/device-token", headers=headers_for)
        assert r.status_code == 201
        body = r.json()
        assert body["token"].startswith("whsk_")
        assert body["last4"] == body["token"][-4:]
        assert "created_at" in body

    def test_post_rotates_existing(self, client, headers_for):
        first = client.post("/api/auth/device-token", headers=headers_for).json()
        second = client.post("/api/auth/device-token", headers=headers_for).json()
        assert first["token"] != second["token"]

    def test_get_returns_exists_false_when_none(self, client, headers_for):
        r = client.get("/api/auth/device-token", headers=headers_for)
        assert r.status_code == 200
        assert r.json() == {"exists": False}

    def test_get_returns_metadata_after_create(self, client, headers_for):
        created = client.post("/api/auth/device-token", headers=headers_for).json()
        r = client.get("/api/auth/device-token", headers=headers_for)
        assert r.status_code == 200
        body = r.json()
        assert body["exists"] is True
        assert body["last4"] == created["last4"]
        assert "token" not in body

    def test_delete_returns_false_when_no_token(self, client, headers_for):
        r = client.delete("/api/auth/device-token", headers=headers_for)
        assert r.status_code == 200
        assert r.json() == {"deleted": False}

    def test_delete_returns_true_after_create(self, client, headers_for):
        client.post("/api/auth/device-token", headers=headers_for)
        r = client.delete("/api/auth/device-token", headers=headers_for)
        assert r.status_code == 200
        assert r.json() == {"deleted": True}
        meta = client.get("/api/auth/device-token", headers=headers_for).json()
        assert meta == {"exists": False}
