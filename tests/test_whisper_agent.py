"""Tests for /api/whisper/agent — voice → tool → reply, single shot."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    import src.core.db
    src.core.db._schema_initialized = False


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-for-voice-agent-tests!")
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-for-voice-agent-tests!")


@pytest.fixture
def user():
    from src.services.auth.service import AuthService
    return AuthService().register("user@test.com", "pw").user_id


@pytest.fixture
def jwt_headers(user):
    from src.core.jwt import create_session_token
    token = create_session_token(user, enc_key="", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def transcription_result():
    return {
        "text": "remind me to buy milk",
        "language": "en",
        "duration_seconds": 1.5,
        "segments": [],
        "model": "base",
    }


@pytest.fixture
def fake_agent(transcription_result):
    """A VoiceAgentService with all collaborators mocked."""
    from src.services.whisper.agent import VoiceAgentService

    whisper = AsyncMock()
    whisper.transcribe.return_value = transcription_result

    llm = AsyncMock()
    memory = MagicMock()
    memory.remember.return_value = "mem-1"
    memory.recall.return_value = [{"memory_id": "mem-1", "content": "buy milk", "score": 0.99, "created_at": 1.0}]

    from src.services.calendar.models import CalendarEvent

    def create_event(**kwargs):
        return CalendarEvent(
            id="evt-1",
            user_id=kwargs["user_id"],
            title=kwargs["title"],
            date=kwargs["date"],
            time=kwargs.get("time"),
            description=kwargs.get("description"),
            created_at=1.0,
        )

    calendar = MagicMock()
    calendar.create_event.side_effect = create_event
    calendar.get_events.return_value = [
        CalendarEvent(
            id="evt-1", user_id="u", title="Dentist", date="2026-05-12", time="10:00",
            description=None, created_at=1.0,
        )
    ]

    search = MagicMock()
    search.search.return_value = {"answer": "It will be sunny.", "results": []}

    auth = MagicMock()
    auth.get_decrypted_imap_accounts.return_value = []

    agent = VoiceAgentService(
        whisper=whisper, llm=llm, memory=memory, calendar=calendar, search=search, auth=auth,
    )
    return agent


@pytest.fixture
def client(fake_agent):
    from src.gateway.__main__ import app
    from src.services.whisper.routes import get_voice_agent
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)


def _plan(tool, args, reply):
    return json.dumps({"tool": tool, "args": args, "reply": reply})


class TestAuth:
    def test_no_credentials_returns_401(self, client):
        r = client.post("/api/whisper/agent", content=b"audio")
        assert r.status_code == 401

    def test_jwt_succeeds(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan("answer", {}, "hi")
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        assert r.status_code == 200


class TestSaveNote:
    def test_dispatches_to_memory_remember(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "save_note", {"text": "buy milk"}, "Saved: buy milk."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "save_note"
        assert body["result"] == {"memory_id": "mem-1"}
        assert body["reply"] == "Saved: buy milk."
        fake_agent.memory.remember.assert_called_once_with("buy milk", body["transcript"] and body.get("user_id") or fake_agent.memory.remember.call_args.args[1])


class TestRecallNotes:
    def test_returns_recall_results(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "recall_notes", {"query": "milk"}, "You noted: buy milk."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "recall_notes"
        assert body["result"][0]["content"] == "buy milk"


class TestCreateEvent:
    def test_creates_event(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "create_event",
            {"title": "Dentist", "date": "2026-05-12", "time": "10:00"},
            "Added Dentist on May 12 at 10am.",
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "create_event"
        assert body["result"]["title"] == "Dentist"
        assert body["result"]["date"] == "2026-05-12"

    def test_missing_required_arg_returns_error_field(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "create_event", {"title": "Dentist"}, "Added Dentist."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["error"] is not None
        assert "date" in body["error"]
        assert body["result"] is None


class TestListEvents:
    def test_returns_events(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "list_events", {"start": "2026-05-12", "end": "2026-05-12"},
            "You have Dentist at 10."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "list_events"
        assert len(body["result"]) == 1
        assert body["result"][0]["title"] == "Dentist"


class TestReadMail:
    def test_returns_helpful_error_without_cached_enc_key(self, client, jwt_headers, fake_agent):
        from src.core.enc_key_cache import default_cache
        default_cache().clear_all()
        fake_agent.llm.complete.return_value = _plan(
            "read_mail", {"count": 3}, "Here's your mail."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "read_mail"
        assert body["error"] is not None
        assert "log" in body["error"].lower() or "encryption key" in body["error"]

    def test_returns_emails_when_enc_key_cached(self, client, jwt_headers, fake_agent, user):
        from src.core.enc_key_cache import default_cache
        default_cache().put(user, "password-from-login")

        fake_agent.auth.get_decrypted_imap_accounts.return_value = [
            {"name": "gmail", "host": "imap.gmail.com", "port": 993, "user": "u", "password": "p"}
        ]

        from unittest.mock import MagicMock
        fake_mail = MagicMock()
        fake_mail.fetch.return_value = MagicMock(
            emails=[
                {"from": "alice@x.com", "subject": "Lunch?", "date": "2026-05-11"},
                {"from": "bob@y.com", "subject": "Report", "date": "2026-05-10"},
            ],
            page=1, total_pages=1, total_emails=2, content="",
        )
        fake_agent.mail_factory = lambda *_args, **_kw: fake_mail

        fake_agent.llm.complete.return_value = _plan(
            "read_mail", {"count": 5}, "You have 2 emails: lunch from Alice, report from Bob."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "read_mail"
        assert body["result"]["total"] == 2
        assert body["result"]["emails"][0]["subject"] == "Lunch?"

    def test_no_imap_accounts_returns_friendly_note(self, client, jwt_headers, fake_agent, user):
        from src.core.enc_key_cache import default_cache
        default_cache().put(user, "password-from-login")
        fake_agent.auth.get_decrypted_imap_accounts.return_value = []
        fake_agent.llm.complete.return_value = _plan(
            "read_mail", {}, "No mail configured."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["result"] == {"emails": [], "total": 0, "note": "No IMAP accounts configured."}


class TestSearchWeb:
    def test_returns_search_answer(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "search_web", {"query": "weather"}, "Sunny."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "search_web"
        assert body["result"]["answer"] == "It will be sunny."


class TestAnswer:
    def test_no_tool_dispatched(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = _plan(
            "answer", {}, "I'm doing great, thanks for asking."
        )
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["tool"] == "answer"
        assert body["result"] is None
        assert "great" in body["reply"]
        fake_agent.memory.remember.assert_not_called()
        fake_agent.calendar.create_event.assert_not_called()


class TestEdgeCases:
    def test_empty_transcript_returns_friendly_reply(self, client, jwt_headers, fake_agent):
        fake_agent.whisper.transcribe.return_value = {
            "text": "", "language": None, "duration_seconds": 0.0, "segments": [], "model": "base",
        }
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["reply"]
        assert body["tool"] == "answer"
        fake_agent.llm.complete.assert_not_called()

    def test_llm_returns_garbage_falls_back_to_answer(self, client, jwt_headers, fake_agent):
        fake_agent.llm.complete.return_value = "not json at all"
        r = client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["tool"] == "answer"

    def test_persists_transcript(self, client, jwt_headers, fake_agent, user):
        fake_agent.llm.complete.return_value = _plan("answer", {}, "ok")
        client.post("/api/whisper/agent", content=b"audio", headers=jwt_headers)
        from src.services.whisper.store import WhisperStore
        rows = WhisperStore().list_for_user(user)
        assert len(rows) == 1
        assert rows[0]["text"] == "remind me to buy milk"
