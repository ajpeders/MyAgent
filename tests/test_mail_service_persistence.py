import json
from pathlib import Path
from unittest.mock import patch

import pytest

import src.core.db
from src.core.db import _connect
from src.gateway.session import SessionState
from src.services.auth.store import UserStore
from src.services.mail.errors import EmailNotFoundError
from src.services.mail.service import MailService


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", Path(tmp_path / "test.db"))
    src.core.db._schema_initialized = False


def test_fetch_persists_messages_and_restores_them():
    user_id = UserStore().create_user("mail@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        service = MailService(state, enc_key="pw123")
        result = service.fetch(count=10, account="Personal")

    assert result.total_emails == 1
    assert result.emails[0]["summary"] == "Deployment report."
    assert result.emails[0]["recommended_todo"] == "Review deploy status."

    restored = MailService(SessionState(session_id="s2", user_id=user_id), enc_key="pw123")
    page = restored.current_page(page=0)

    assert page.total_emails == 1
    assert page.emails[0]["subject"] == "Server report"
    assert page.emails[0]["summary"] == "Deployment report."
    assert page.emails[0]["recommended_todo"] == "Review deploy status."


def test_read_restores_message_from_persisted_store():
    user_id = UserStore().create_user("mail-read@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        MailService(state, enc_key="pw123").fetch(count=10, account="Personal")

    detail = MailService(SessionState(session_id="s2", user_id=user_id), enc_key="pw123").read(1)

    assert detail.subject == "Server report"
    assert detail.body == "Deploy completed successfully."
    assert detail.summary == "Deployment report."


def test_refetch_preserves_saved_summary_and_recommendation_without_reanalyzing():
    user_id = UserStore().create_user("mail-refetch@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        MailService(state, enc_key="pw123").fetch(count=10, account="Personal")
        assert mock_llm.complete_sync.call_count == 1

    state2 = SessionState(
        session_id="s2",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    with patch("src.core.mail_engine.mail_read_emails", return_value=[dict(fetched[0])]), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        result = MailService(state2, enc_key="pw123").fetch(count=10, account="Personal")

    assert result.emails[0]["recommendation"] == "review"
    assert result.emails[0]["summary"] == "Deployment report."
    assert result.emails[0]["recommended_todo"] == "Review deploy status."
    assert mock_llm.complete_sync.call_count == 0


def test_delete_removes_message_from_persisted_message_store():
    user_id = UserStore().create_user("mail-delete@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        service = MailService(state, enc_key="pw123")
        service.fetch(count=10, account="Personal")

    with patch("src.core.mail_engine.mail_move_by_uids", return_value=1):
        service.move([1], "Trash")

    restored = MailService(SessionState(session_id="s2", user_id=user_id), enc_key="pw123")
    with pytest.raises(Exception):
        restored.read(1)


def test_mark_read_updates_persisted_message_state():
    user_id = UserStore().create_user("mail-seen@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        service = MailService(state, enc_key="pw123")
        service.fetch(count=10, account="Personal")

    with patch("src.core.actions.mail.mark_read_by_uids", return_value=1):
        service.mark_read(1)

    restored = MailService(SessionState(session_id="s2", user_id=user_id), enc_key="pw123")
    page = restored.current_page(page=0)
    assert page.emails[0]["read"] is True


def test_refetch_normalizes_legacy_keep_recommendation_to_review():
    user_id = UserStore().create_user("mail-legacy@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "keep", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        MailService(state, enc_key="pw123").fetch(count=10, account="Personal")

    state2 = SessionState(
        session_id="s2",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    with patch("src.core.mail_engine.mail_read_emails", return_value=[dict(fetched[0])]), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        result = MailService(state2, enc_key="pw123").fetch(count=10, account="Personal")

    assert result.emails[0]["recommendation"] == "review"
    assert mock_llm.complete_sync.call_count == 0


def test_record_feedback_logs_action():
    user_id = UserStore().create_user("mail-feedback@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        service = MailService(state, enc_key="pw123")
        service.fetch(count=10, account="Personal")

    service.record_feedback(1, "good", "helpful recommendation")

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT action, feedback_text, email_subject FROM email_actions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "feedback:good"
    assert row[1] == "helpful recommendation"
    assert row[2] == "Server report"


def test_record_feedback_bad_index_raises():
    user_id = UserStore().create_user("mail-badfb@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        service = MailService(state, enc_key="pw123")
        service.fetch(count=10, account="Personal")

    with pytest.raises(EmailNotFoundError):
        service.record_feedback(99, "bad")


def test_feedback_influences_subsequent_analysis_guidance():
    user_id = UserStore().create_user("mail-guidance@test.com", "pw123")
    state = SessionState(
        session_id="s1",
        user_id=user_id,
        imap_accounts=[{"name": "Personal", "host": "imap.example.com", "user": "me", "password": "pw"}],
    )
    fetched = [{
        "uid": 101,
        "uidvalidity": "777",
        "message_id": "<abc@test>",
        "from": "ops@example.com",
        "subject": "Server report",
        "date": "2026-04-26",
        "body": "Deploy completed successfully.",
        "account": "Personal",
        "mailbox": "INBOX",
        "read": False,
    }]

    with patch("src.core.mail_engine.mail_read_emails", return_value=fetched), \
         patch("src.core.mail_engine.mail_refresh"), \
         patch("src.core.mail_engine.default_adapter") as mock_llm:
        mock_llm.complete_sync.return_value = json.dumps({
            "recommendations": [
                {"index": 1, "action": "review", "summary": "Deployment report.", "todo": "Review deploy status."}
            ]
        })
        service = MailService(state, enc_key="pw123")
        service.fetch(count=10, account="Personal")

    service.record_feedback(1, "bad", "too aggressive on delete")

    guidance = service._feedback_guidance()
    assert "rejected" in guidance
    assert "too aggressive on delete" in guidance
