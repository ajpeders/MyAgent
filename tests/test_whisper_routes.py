"""Tests for /api/whisper/* — dual auth, persistence, list, delete, size cap."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    import src.core.db
    src.core.db._schema_initialized = False


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-for-whisper-route-tests!")
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-for-whisper-route-tests!")


@pytest.fixture
def auth_service():
    from src.services.auth.service import AuthService
    return AuthService()


@pytest.fixture
def user(auth_service):
    return auth_service.register("user@test.com", "pw").user_id


@pytest.fixture
def other_user(auth_service):
    return auth_service.register("other@test.com", "pw").user_id


@pytest.fixture
def jwt_headers(user):
    from src.core.jwt import create_session_token
    token = create_session_token(user, enc_key="", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_jwt_headers(other_user):
    from src.core.jwt import create_session_token
    token = create_session_token(other_user, enc_key="", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def device_token_headers(auth_service, user):
    result = auth_service.generate_device_token(user)
    return {"X-Device-Token": result["token"]}


@pytest.fixture
def mock_whisper():
    fake_result = {
        "text": "hello world",
        "language": "en",
        "duration_seconds": 1.5,
        "segments": [{"start": 0.0, "end": 1.5, "text": "hello world"}],
        "model": "base",
    }
    mock_service = AsyncMock()
    mock_service.transcribe.return_value = fake_result
    return mock_service


@pytest.fixture
def client(mock_whisper):
    from src.gateway.__main__ import app
    from src.services.whisper.routes import get_whisper_service
    app.dependency_overrides[get_whisper_service] = lambda: mock_whisper
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_whisper_service, None)


class TestAuthOnTranscribe:
    def test_no_credentials_returns_401(self, client):
        r = client.post("/api/whisper/transcribe", content=b"audio")
        assert r.status_code == 401

    def test_invalid_jwt_falls_through_to_device_token(self, client):
        r = client.post(
            "/api/whisper/transcribe",
            content=b"audio",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert r.status_code == 401

    def test_invalid_device_token_returns_401(self, client):
        r = client.post(
            "/api/whisper/transcribe",
            content=b"audio",
            headers={"X-Device-Token": "whsk_does_not_exist"},
        )
        assert r.status_code == 401

    def test_jwt_succeeds(self, client, jwt_headers):
        r = client.post("/api/whisper/transcribe", content=b"audio", headers=jwt_headers)
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"

    def test_device_token_succeeds(self, client, device_token_headers):
        r = client.post("/api/whisper/transcribe", content=b"audio", headers=device_token_headers)
        assert r.status_code == 200
        assert r.json()["text"] == "hello world"


class TestTranscribeFlow:
    def test_response_includes_transcript_id(self, client, jwt_headers):
        r = client.post("/api/whisper/transcribe", content=b"audio", headers=jwt_headers)
        body = r.json()
        assert body["transcript_id"]
        assert body["captured_at"] is not None
        assert body["source"] == "web"

    def test_device_token_request_marked_as_shortcut_source(self, client, device_token_headers):
        r = client.post("/api/whisper/transcribe", content=b"audio", headers=device_token_headers)
        assert r.json()["source"] == "shortcut"

    def test_persists_to_store(self, client, jwt_headers, user):
        client.post("/api/whisper/transcribe", content=b"audio", headers=jwt_headers)
        from src.services.whisper.store import WhisperStore
        rows = WhisperStore().list_for_user(user)
        assert len(rows) == 1
        assert rows[0]["text"] == "hello world"
        assert rows[0]["source"] == "web"

    def test_size_cap_returns_413(self, client, jwt_headers):
        from src.services.whisper.routes import MAX_AUDIO_BYTES
        big = b"x" * (MAX_AUDIO_BYTES + 1)
        r = client.post("/api/whisper/transcribe", content=big, headers=jwt_headers)
        assert r.status_code == 413

    def test_empty_audio_returns_400(self, client, jwt_headers, mock_whisper):
        from src.services.whisper.errors import TranscriptionError
        mock_whisper.transcribe.side_effect = TranscriptionError("Audio payload is empty")
        r = client.post("/api/whisper/transcribe", content=b"", headers=jwt_headers)
        assert r.status_code == 400

    def test_config_error_returns_503(self, client, jwt_headers, mock_whisper):
        from src.services.whisper.errors import WhisperConfigError
        mock_whisper.transcribe.side_effect = WhisperConfigError("faster-whisper missing")
        r = client.post("/api/whisper/transcribe", content=b"audio", headers=jwt_headers)
        assert r.status_code == 503


class TestListTranscripts:
    def test_requires_jwt(self, client, device_token_headers):
        r = client.get("/api/whisper/transcripts", headers=device_token_headers)
        assert r.status_code == 401

    def test_empty_list(self, client, jwt_headers):
        r = client.get("/api/whisper/transcripts", headers=jwt_headers)
        assert r.status_code == 200
        assert r.json() == {"transcripts": []}

    def test_returns_newest_first(self, client, jwt_headers):
        client.post("/api/whisper/transcribe", content=b"a", headers=jwt_headers)
        client.post("/api/whisper/transcribe", content=b"b", headers=jwt_headers)
        client.post("/api/whisper/transcribe", content=b"c", headers=jwt_headers)
        body = client.get("/api/whisper/transcripts", headers=jwt_headers).json()
        ts = body["transcripts"]
        assert len(ts) == 3
        assert ts[0]["captured_at"] >= ts[1]["captured_at"] >= ts[2]["captured_at"]

    def test_isolated_per_user(self, client, jwt_headers, other_jwt_headers):
        client.post("/api/whisper/transcribe", content=b"a", headers=jwt_headers)
        client.post("/api/whisper/transcribe", content=b"b", headers=other_jwt_headers)
        mine = client.get("/api/whisper/transcripts", headers=jwt_headers).json()
        theirs = client.get("/api/whisper/transcripts", headers=other_jwt_headers).json()
        assert len(mine["transcripts"]) == 1
        assert len(theirs["transcripts"]) == 1
        assert mine["transcripts"][0]["transcript_id"] != theirs["transcripts"][0]["transcript_id"]


class TestDeleteTranscript:
    def test_requires_jwt(self, client, device_token_headers):
        r = client.delete("/api/whisper/transcripts/anything", headers=device_token_headers)
        assert r.status_code == 401

    def test_unknown_id_returns_404(self, client, jwt_headers):
        r = client.delete("/api/whisper/transcripts/not-real", headers=jwt_headers)
        assert r.status_code == 404

    def test_deletes_own(self, client, jwt_headers):
        created = client.post("/api/whisper/transcribe", content=b"a", headers=jwt_headers).json()
        r = client.delete(f"/api/whisper/transcripts/{created['transcript_id']}", headers=jwt_headers)
        assert r.status_code == 200
        assert r.json() == {"deleted": True}
        body = client.get("/api/whisper/transcripts", headers=jwt_headers).json()
        assert body["transcripts"] == []

    def test_cannot_delete_other_users(self, client, jwt_headers, other_jwt_headers):
        created = client.post("/api/whisper/transcribe", content=b"a", headers=jwt_headers).json()
        r = client.delete(
            f"/api/whisper/transcripts/{created['transcript_id']}",
            headers=other_jwt_headers,
        )
        assert r.status_code == 404
