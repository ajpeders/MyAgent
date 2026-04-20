"""Tests for core.crypto and core.db modules."""
import json
import pytest
from pathlib import Path

from cryptography.exceptions import InvalidTag

from core.crypto import encrypt_payload, decrypt_payload, hash_password, verify_password
from core.db import UserStore, SessionStore, EmailCacheStore, SessionState


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file so tests never touch the real database."""
    monkeypatch.setattr("core.db.DB_PATH", tmp_path / "test.db")


@pytest.fixture
def user_store():
    return UserStore()


@pytest.fixture
def session_store():
    return SessionStore()


@pytest.fixture
def email_cache_store():
    return EmailCacheStore()


# ── Crypto: encrypt / decrypt ────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    data = {"host": "imap.example.com", "port": 993, "user": "alice"}
    password = "hunter2"
    encrypted = encrypt_payload(data, password)
    assert set(encrypted.keys()) == {"salt", "iv", "data"}
    assert decrypt_payload(encrypted, password) == data


def test_decrypt_wrong_password():
    data = {"secret": "value"}
    encrypted = encrypt_payload(data, "correct-password")
    with pytest.raises(InvalidTag):
        decrypt_payload(encrypted, "wrong-password")


# ── Crypto: hash / verify ───────────────────────────────────────────────────


def test_hash_verify_roundtrip():
    password = "s3cret!"
    stored = hash_password(password)
    assert set(stored.keys()) == {"salt", "hash"}
    assert verify_password(password, stored) is True


def test_verify_wrong_password():
    stored = hash_password("correct")
    assert verify_password("wrong", stored) is False


# ── UserStore ────────────────────────────────────────────────────────────────


def test_create_and_get_user_by_email(user_store):
    uid = user_store.create_user("Alice@Example.com", "pw123")
    user = user_store.get_user_by_email("alice@example.com")
    assert user is not None
    assert user["user_id"] == uid
    assert user["email"] == "alice@example.com"


def test_get_user_by_id(user_store):
    uid = user_store.create_user("bob@test.com", "pw")
    user = user_store.get_user_by_id(uid)
    assert user is not None
    assert user["user_id"] == uid


def test_get_user_not_found(user_store):
    assert user_store.get_user_by_email("nobody@test.com") is None
    assert user_store.get_user_by_id("nonexistent-id") is None


def test_user_verify_password(user_store):
    uid = user_store.create_user("carol@test.com", "mypass")
    assert user_store.verify_password(uid, "mypass") is True
    assert user_store.verify_password(uid, "wrong") is False


def test_update_imap_creds(user_store):
    uid = user_store.create_user("dave@test.com", "pw")
    creds = [{"host": "imap.gmail.com", "user": "dave"}]
    user_store.update_imap_creds(uid, creds)
    user = user_store.get_user_by_id(uid)
    assert user["encrypted_imap_creds"] is not None
    stored = json.loads(user["encrypted_imap_creds"])
    assert stored == creds


def test_delete_user(user_store):
    uid = user_store.create_user("ephemeral@test.com", "pw")
    user_store.delete_user(uid)
    assert user_store.get_user_by_id(uid) is None


def test_delete_user_cascades_sessions(user_store, session_store):
    uid = user_store.create_user("cascade@test.com", "pw")
    sid = session_store.create_session(uid)
    user_store.delete_user(uid)
    assert session_store.get_session(sid) is None


# ── SessionStore ─────────────────────────────────────────────────────────────


def test_create_and_get_session(user_store, session_store):
    uid = user_store.create_user("sess@test.com", "pw")
    sid = session_store.create_session(uid)
    state = session_store.get_session(sid)
    assert state is not None
    assert state.session_id == sid
    assert state.user_id == uid
    assert state.mail_engine is None
    assert state.imap_accounts is None


def test_create_session_with_imap_accounts(user_store, session_store):
    uid = user_store.create_user("imap@test.com", "pw")
    accounts = [{"host": "imap.example.com", "user": "u"}]
    sid = session_store.create_session(uid, imap_accounts=accounts)
    state = session_store.get_session(sid)
    assert state.imap_accounts == accounts


def test_save_session(user_store, session_store):
    uid = user_store.create_user("save@test.com", "pw")
    sid = session_store.create_session(uid)
    state = session_store.get_session(sid)
    state.mail_engine = {"inbox": [{"uid": 1, "subject": "Hi"}]}
    session_store.save_session(state)
    reloaded = session_store.get_session(sid)
    assert reloaded.mail_engine == {"inbox": [{"uid": 1, "subject": "Hi"}]}


def test_delete_session(user_store, session_store):
    uid = user_store.create_user("delsess@test.com", "pw")
    sid = session_store.create_session(uid)
    session_store.delete_session(sid)
    assert session_store.get_session(sid) is None


def test_get_session_not_found(session_store):
    assert session_store.get_session("no-such-id") is None


# ── EmailCacheStore ──────────────────────────────────────────────────────────


def test_set_and_get_cached_emails(user_store, email_cache_store):
    uid = user_store.create_user("cache@test.com", "pw")
    emails = [{"uid": 1, "subject": "Hello"}, {"uid": 2, "subject": "World"}]
    email_cache_store.set_cached_emails(uid, "work", "INBOX", emails, "pw")
    result = email_cache_store.get_cached_emails(uid, "work", "INBOX", "pw")
    assert result == emails


def test_get_cached_emails_missing(user_store, email_cache_store):
    uid = user_store.create_user("nocache@test.com", "pw")
    assert email_cache_store.get_cached_emails(uid, "x", "INBOX", "pw") is None


def test_invalidate_cache(user_store, email_cache_store):
    uid = user_store.create_user("inv@test.com", "pw")
    email_cache_store.set_cached_emails(uid, "acct", "INBOX", [{"uid": 1}], "pw")
    email_cache_store.invalidate(uid, "acct", "INBOX")
    assert email_cache_store.get_cached_emails(uid, "acct", "INBOX", "pw") is None
