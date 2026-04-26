"""Tests covering audit gaps: IMAP credential CRUD, auth bypass, cross-user isolation."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from src.services.auth.models import ImapAccount
from src.services.auth.service import AuthService
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
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-key-32-bytes-long!!")
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-key-32-bytes-long!!")


@pytest.fixture
def auth():
    return AuthService()


@pytest.fixture
def account_gmail():
    return ImapAccount(
        name="Gmail",
        server="imap.gmail.com",
        port=993,
        username="user@gmail.com",
        imap_password="gmail-pass-123",
    )


@pytest.fixture
def account_yahoo():
    return ImapAccount(
        name="Yahoo",
        server="imap.mail.yahoo.com",
        port=993,
        username="user@yahoo.com",
        imap_password="yahoo-pass-456",
    )


# ── IMAP credential CRUD round-trip ─────────────────────────────────────────


class TestImapCrud:
    def test_add_account_then_list(self, auth, account_gmail):
        result = auth.register("alice@test.com", "password123")
        enc_key = "password123"

        auth.add_imap_account(result.user_id, account_gmail, enc_key)
        accounts = auth.list_imap_accounts(result.user_id)

        assert len(accounts) == 1
        assert accounts[0].name == "Gmail"

    def test_add_two_accounts(self, auth, account_gmail, account_yahoo):
        result = auth.register("bob@test.com", "password123")
        enc_key = "password123"

        auth.add_imap_account(result.user_id, account_gmail, enc_key)
        auth.add_imap_account(result.user_id, account_yahoo, enc_key)
        accounts = auth.list_imap_accounts(result.user_id)

        assert len(accounts) == 2
        assert accounts[0].name == "Gmail"
        assert accounts[1].name == "Yahoo"

    def test_add_then_login_decrypts(self, auth, account_gmail):
        """Full round-trip: register → add IMAP → login decrypts credentials."""
        password = "password123"
        reg = auth.register("carol@test.com", password)
        auth.add_imap_account(reg.user_id, account_gmail, password)

        login_result = auth.login("carol@test.com", password)
        assert login_result.user_id == reg.user_id

    def test_update_account(self, auth, account_gmail):
        result = auth.register("dave@test.com", "password123")
        enc_key = "password123"
        auth.add_imap_account(result.user_id, account_gmail, enc_key)

        updated = ImapAccount(
            name="Gmail-Updated",
            server="imap.gmail.com",
            port=993,
            username="new-user@gmail.com",
            imap_password="new-pass",
        )
        auth.update_imap_account(result.user_id, 0, updated, enc_key)
        accounts = auth.list_imap_accounts(result.user_id)

        assert len(accounts) == 1
        assert accounts[0].name == "Gmail-Updated"

    def test_delete_account(self, auth, account_gmail, account_yahoo):
        result = auth.register("eve@test.com", "password123")
        enc_key = "password123"
        auth.add_imap_account(result.user_id, account_gmail, enc_key)
        auth.add_imap_account(result.user_id, account_yahoo, enc_key)

        deleted = auth.delete_imap_account(result.user_id, 0)
        assert deleted is True
        accounts = auth.list_imap_accounts(result.user_id)
        assert len(accounts) == 1
        assert accounts[0].name == "Yahoo"

    def test_delete_nonexistent_account(self, auth):
        result = auth.register("frank@test.com", "password123")
        deleted = auth.delete_imap_account(result.user_id, 99)
        assert deleted is False

    def test_list_empty_accounts(self, auth):
        result = auth.register("grace@test.com", "password123")
        accounts = auth.list_imap_accounts(result.user_id)
        assert accounts == []


# ── Auth bypass: JWT required on all protected routes ────────────────────────


class DummyRequest:
    def __init__(self, headers=None, query_params=None):
        self._headers = headers or {}
        self._query_params = query_params or {}

    @property
    def headers(self):
        return MagicMock(get=lambda key, default=None: self._headers.get(key, default))

    @property
    def query_params(self):
        return MagicMock(get=lambda key, default=None: self._query_params.get(key, default))

    async def body(self):
        return b'{"prompt":"hi"}'


class TestAuthBypass:
    """Verify that routes reject requests without valid JWT."""

    def test_memory_add_rejects_without_jwt(self):
        from src.gateway.routes.memory import memory_add, MemoryAddRequest
        req = DummyRequest()
        with pytest.raises(HTTPException) as exc:
            memory_add(req, MemoryAddRequest(content="test"))
        assert exc.value.status_code == 401

    def test_memory_list_rejects_without_jwt(self):
        from src.gateway.routes.memory import memory_list
        req = DummyRequest()
        with pytest.raises(HTTPException) as exc:
            memory_list(req)
        assert exc.value.status_code == 401

    def test_memory_delete_rejects_without_jwt(self):
        from src.gateway.routes.memory import memory_delete
        req = DummyRequest()
        with pytest.raises(HTTPException) as exc:
            memory_delete(req, "some-id")
        assert exc.value.status_code == 401

    def test_mail_get_rejects_without_jwt(self):
        from src.gateway.routes.mail import mail_get
        req = DummyRequest(query_params={"session_id": "s1"})
        with pytest.raises(HTTPException) as exc:
            mail_get(req)
        assert exc.value.status_code == 401

    def test_chat_rejects_without_jwt(self):
        import asyncio
        from src.gateway.routes.chat import chat
        req = DummyRequest()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(chat(req))
        assert exc.value.status_code == 401

    def test_x_user_id_header_alone_is_not_enough(self):
        """Setting X-User-ID without a JWT must still be rejected."""
        from src.gateway.routes.memory import memory_list
        req = DummyRequest(headers={"X-User-ID": "some-user"})
        with pytest.raises(HTTPException) as exc:
            memory_list(req)
        assert exc.value.status_code == 401


# ── Cross-user data isolation ────────────────────────────────────────────────


class TestCrossUserIsolation:
    """Verify that user A's IMAP credentials are not visible to user B."""

    def test_imap_accounts_isolated_between_users(self, auth, account_gmail, account_yahoo):
        alice = auth.register("alice-iso@test.com", "pass-a")
        bob = auth.register("bob-iso@test.com", "pass-b")

        auth.add_imap_account(alice.user_id, account_gmail, "pass-a")
        auth.add_imap_account(bob.user_id, account_yahoo, "pass-b")

        alice_accounts = auth.list_imap_accounts(alice.user_id)
        bob_accounts = auth.list_imap_accounts(bob.user_id)

        assert len(alice_accounts) == 1
        assert alice_accounts[0].name == "Gmail"
        assert len(bob_accounts) == 1
        assert bob_accounts[0].name == "Yahoo"

    def test_delete_does_not_affect_other_user(self, auth, account_gmail):
        alice = auth.register("alice-del@test.com", "pass-a")
        bob = auth.register("bob-del@test.com", "pass-b")

        auth.add_imap_account(alice.user_id, account_gmail, "pass-a")
        auth.add_imap_account(bob.user_id, account_gmail, "pass-b")

        auth.delete_imap_account(alice.user_id, 0)

        alice_accounts = auth.list_imap_accounts(alice.user_id)
        bob_accounts = auth.list_imap_accounts(bob.user_id)

        assert len(alice_accounts) == 0
        assert len(bob_accounts) == 1

    def test_login_decrypts_only_own_credentials(self, auth, account_gmail, account_yahoo):
        """Each user's credentials are encrypted with their own password."""
        alice = auth.register("alice-enc@test.com", "alice-pass")
        bob = auth.register("bob-enc@test.com", "bob-pass")

        auth.add_imap_account(alice.user_id, account_gmail, "alice-pass")
        auth.add_imap_account(bob.user_id, account_yahoo, "bob-pass")

        # Login as Alice — should only see Gmail
        alice_login = auth.login("alice-enc@test.com", "alice-pass")
        assert alice_login.user_id == alice.user_id

        # Login as Bob — should only see Yahoo
        bob_login = auth.login("bob-enc@test.com", "bob-pass")
        assert bob_login.user_id == bob.user_id
