"""Tests for /api/whisper/agent/async + GET /api/whisper/jobs/{id}."""
import asyncio
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
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-for-async-agent-tests!")
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-for-async-agent-tests!")


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
def fake_agent():
    agent = AsyncMock()
    agent.handle.return_value = {
        "transcript_id": "t-1",
        "transcript": "remind me to buy milk",
        "tool": "save_note",
        "args": {"text": "buy milk"},
        "result": {"memory_id": "m-1"},
        "reply": "Saved.",
        "error": None,
        "captured_at": 1.0,
    }
    return agent


@pytest.fixture
def fake_notifier():
    n = AsyncMock()
    n.enabled = True
    return n


@pytest.fixture
def client(fake_agent, fake_notifier):
    from src.gateway.__main__ import app
    from src.services.whisper.routes import get_voice_agent, get_notifier
    app.dependency_overrides[get_voice_agent] = lambda: fake_agent
    app.dependency_overrides[get_notifier] = lambda: fake_notifier
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_voice_agent, None)
        app.dependency_overrides.pop(get_notifier, None)


async def _wait_for_job(client, jwt_headers, job_id, timeout=2.0):
    """Poll until job is done or fail."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        r = client.get(f"/api/whisper/jobs/{job_id}", headers=jwt_headers)
        if r.status_code == 200 and r.json()["status"] in ("done", "failed"):
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError("job did not complete in time")


class TestAsyncEndpoint:
    def test_requires_auth(self, client):
        r = client.post("/api/whisper/agent/async", content=b"audio")
        assert r.status_code == 401

    def test_returns_202_with_job_id(self, client, jwt_headers):
        r = client.post("/api/whisper/agent/async", content=b"audio", headers=jwt_headers)
        assert r.status_code == 202
        body = r.json()
        assert body["job_id"]
        assert body["status"] == "pending"
        assert body["push_enabled"] is True

    def test_size_cap_413(self, client, jwt_headers):
        from src.services.whisper.routes import MAX_AUDIO_BYTES
        r = client.post("/api/whisper/agent/async", content=b"x" * (MAX_AUDIO_BYTES + 1), headers=jwt_headers)
        assert r.status_code == 413


class TestJobLifecycle:
    @pytest.mark.asyncio
    async def test_completes_and_publishes(self, client, jwt_headers, fake_agent, fake_notifier):
        r = client.post("/api/whisper/agent/async", content=b"audio", headers=jwt_headers)
        job_id = r.json()["job_id"]
        done = await _wait_for_job(client, jwt_headers, job_id)
        assert done["status"] == "done"
        assert done["reply"] == "Saved."
        assert done["tool"] == "save_note"
        fake_agent.handle.assert_awaited_once()
        fake_notifier.publish.assert_awaited_once()
        published = fake_notifier.publish.call_args
        assert published.args[0] == "Saved."

    @pytest.mark.asyncio
    async def test_failure_marks_failed_and_notifies(self, client, jwt_headers, fake_agent, fake_notifier):
        fake_agent.handle.side_effect = RuntimeError("kaboom")
        r = client.post("/api/whisper/agent/async", content=b"audio", headers=jwt_headers)
        job_id = r.json()["job_id"]
        done = await _wait_for_job(client, jwt_headers, job_id)
        assert done["status"] == "failed"
        assert "kaboom" in done["error"]
        fake_notifier.publish.assert_awaited_once()


class TestJobPolling:
    def test_unknown_job_returns_404(self, client, jwt_headers):
        r = client.get("/api/whisper/jobs/nope", headers=jwt_headers)
        assert r.status_code == 404

    def test_other_user_cannot_read_job(self, client, jwt_headers):
        from src.services.auth.service import AuthService
        from src.core.jwt import create_session_token
        other_id = AuthService().register("other@test.com", "pw").user_id
        other_token = create_session_token(other_id, enc_key="", is_admin=False)
        r = client.post("/api/whisper/agent/async", content=b"audio", headers=jwt_headers)
        job_id = r.json()["job_id"]
        r2 = client.get(f"/api/whisper/jobs/{job_id}", headers={"Authorization": f"Bearer {other_token}"})
        assert r2.status_code == 404


class TestNtfyDisabled:
    @pytest.fixture
    def disabled_notifier(self):
        n = AsyncMock()
        n.enabled = False
        return n

    @pytest.fixture
    def client_no_push(self, fake_agent, disabled_notifier):
        from src.gateway.__main__ import app
        from src.services.whisper.routes import get_voice_agent, get_notifier
        app.dependency_overrides[get_voice_agent] = lambda: fake_agent
        app.dependency_overrides[get_notifier] = lambda: disabled_notifier
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_voice_agent, None)
            app.dependency_overrides.pop(get_notifier, None)

    def test_push_disabled_flag(self, client_no_push, jwt_headers):
        r = client_no_push.post("/api/whisper/agent/async", content=b"audio", headers=jwt_headers)
        assert r.json()["push_enabled"] is False
