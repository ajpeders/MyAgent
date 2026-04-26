"""Tests for admin auth — is_admin flag, ADMIN_EMAILS auto-promote, middleware."""
import pytest
from unittest.mock import patch
from fastapi import HTTPException

from src.gateway.session import SessionState


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    from pathlib import Path
    db_path = Path(tmp_path / "test.db")
    monkeypatch.setattr("src.core.db.DB_PATH", db_path)
    import src.core.db
    src.core.db._schema_initialized = False


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-for-admin-auth-tests!")
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-for-admin-auth-tests!")


@pytest.fixture
def admin_emails(monkeypatch):
    """Set ADMIN_EMAILS to include test@admin.com."""
    monkeypatch.setattr("src.core.config.ADMIN_EMAILS", ["test@admin.com"])
    monkeypatch.setattr("src.services.auth.service.ADMIN_EMAILS", ["test@admin.com"])


# ── UserStore is_admin ───────────────────────────────────────────────────────


class TestUserStoreAdmin:
    def test_new_user_is_not_admin(self):
        from src.services.auth.store import UserStore
        store = UserStore()
        uid = store.create_user("user@test.com", "pw")
        user = store.get_user_by_id(uid)
        assert user["is_admin"] is False

    def test_set_admin_promotes_user(self):
        from src.services.auth.store import UserStore
        store = UserStore()
        uid = store.create_user("user2@test.com", "pw")
        store.set_admin(uid, True)
        user = store.get_user_by_id(uid)
        assert user["is_admin"] is True

    def test_set_admin_demotes_user(self):
        from src.services.auth.store import UserStore
        store = UserStore()
        uid = store.create_user("user3@test.com", "pw")
        store.set_admin(uid, True)
        store.set_admin(uid, False)
        user = store.get_user_by_id(uid)
        assert user["is_admin"] is False


# ── AuthService auto-promote ─────────────────────────────────────────────────


class TestAuthServiceAdmin:
    def test_register_auto_promotes_admin_email(self, admin_emails):
        from src.services.auth.service import AuthService
        from src.core.jwt import decode

        svc = AuthService()
        result = svc.register("test@admin.com", "password123")
        token = decode(result.token)
        assert token["is_admin"] is True

    def test_register_non_admin_email_stays_normal(self, admin_emails):
        from src.services.auth.service import AuthService
        from src.core.jwt import decode

        svc = AuthService()
        result = svc.register("regular@user.com", "password123")
        token = decode(result.token)
        assert token["is_admin"] is False

    def test_login_auto_promotes_admin_email(self, admin_emails):
        from src.services.auth.service import AuthService
        from src.core.jwt import decode

        svc = AuthService()
        svc.register("test@admin.com", "password123")
        result = svc.login("test@admin.com", "password123")
        token = decode(result.token)
        assert token["is_admin"] is True

    def test_login_non_admin_stays_normal(self, admin_emails):
        from src.services.auth.service import AuthService
        from src.core.jwt import decode

        svc = AuthService()
        svc.register("normal@user.com", "password123")
        result = svc.login("normal@user.com", "password123")
        token = decode(result.token)
        assert token["is_admin"] is False


# ── Middleware ────────────────────────────────────────────────────────────────


class DummyRequest:
    def __init__(self, headers: dict | None = None):
        self._headers = headers or {}

    @property
    def headers(self):
        from unittest.mock import MagicMock
        return MagicMock(get=lambda key, default=None: self._headers.get(key, default))


class TestAdminMiddleware:
    def test_admin_required_with_admin_token(self):
        from src.core.jwt import create_session_token
        from src.gateway.middleware import admin_required

        token = create_session_token("u1", enc_key="", is_admin=True)
        req = DummyRequest(headers={"Authorization": f"Bearer {token}"})
        payload = admin_required(req)
        assert payload["is_admin"] is True

    def test_admin_required_rejects_non_admin(self):
        from src.core.jwt import create_session_token
        from src.gateway.middleware import admin_required

        token = create_session_token("u1", enc_key="", is_admin=False)
        req = DummyRequest(headers={"Authorization": f"Bearer {token}"})
        with pytest.raises(HTTPException) as exc:
            admin_required(req)
        assert exc.value.status_code == 403

    def test_admin_required_rejects_no_token(self):
        from src.gateway.middleware import admin_required

        req = DummyRequest()
        with pytest.raises(HTTPException) as exc:
            admin_required(req)
        assert exc.value.status_code == 401
