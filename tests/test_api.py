"""Tests for gateway API endpoints."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.routes.chat import router as chat_router, ChatRequest
from src.gateway.routes.mail import router as mail_router, FetchRequest, MoveRequest
from src.gateway.session import SessionState


class DummyRequest:
    def __init__(self, body_json: str = "", headers: dict | None = None, query_params: dict | None = None):
        self._body = body_json
        self._headers = headers or {}
        self._query_params = query_params or {}

    async def body(self):
        return self._body.encode()

    @property
    def headers(self):
        return MagicMock(get=lambda key, default=None: self._headers.get(key, default))

    @property
    def query_params(self):
        return MagicMock(get=lambda key, default=None: self._query_params.get(key, default))


class ChatEndpointTests(unittest.IsolatedAsyncioTestCase):
    @patch("src.gateway.routes.chat.jwt_required", return_value={"user_id": ""})
    @patch("src.gateway.routes.chat.dispatch_session")
    async def test_chat_without_session_is_stateless(self, dispatch_session, _jwt):
        dispatch_session.return_value = [
            {"type": "answer", "content": "4", "agent": "answer"},
        ]

        from src.gateway.routes.chat import chat
        req = DummyRequest('{"prompt":"what is 2 + 2?","confirm":false}')
        resp = await chat(req)

        self.assertEqual(len(resp), 1)
        self.assertEqual(resp[0].type, "answer")
        self.assertEqual(resp[0].content, "4")
        state = dispatch_session.call_args.args[0]
        self.assertEqual(state.session_id, "_stateless")

    @patch("src.gateway.routes.chat.jwt_required", return_value={"user_id": "test-user"})
    @patch("src.gateway.routes.chat.save_session")
    @patch("src.gateway.routes.chat.load_session")
    @patch("src.gateway.routes.chat.dispatch_session")
    async def test_chat_with_session_loads_and_saves_state(self, dispatch_session, load_session, save_session, _jwt):
        state = SessionState(session_id="mail", user_id="test-user")
        load_session.return_value = state
        dispatch_session.return_value = [
            {
                "type": "mail_list",
                "content": "mail",
                "agent": "mail",
                "emails": [{"index": 1, "subject": "Hello"}],
                "page": 1,
                "total_pages": 1,
                "total_emails": 1,
            },
        ]

        from src.gateway.routes.chat import chat
        req = DummyRequest(
            '{"prompt":"check email","model":"test-model","session_id":"mail"}',
            query_params={"session_id": "mail"},
        )
        resp = await chat(req)

        self.assertEqual(resp[0].emails, [{"index": 1, "subject": "Hello"}])
        self.assertEqual(resp[0].page, 1)
        load_session.assert_called_once_with("mail", user_id="test-user")
        save_session.assert_called_once_with(state)

    def test_health(self):
        from src.gateway.__main__ import health
        self.assertEqual(health(), {"status": "ok"})


class MailEndpointTests(unittest.TestCase):
    def _state_with_inbox(self, emails: list[dict]) -> SessionState:
        from src.core.mail_engine import MailEngine
        engine = MailEngine(model="test")
        engine.inbox = emails
        state = SessionState(session_id="s1", user_id="u1")
        state.mail_engine = engine.to_dict()
        return state

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.gateway.routes.mail.save_session")
    def test_mail_get_returns_inbox_page(self, save_session, load_session, _jwt):
        emails = [{"uid": 1, "from": "a@b.com", "subject": "Hi", "date": "2026-01-01", "body": "", "account": ""}]
        state = self._state_with_inbox(emails)
        load_session.return_value = state

        from src.gateway.routes.mail import mail_get
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_result = MagicMock(
            emails=[{"index": 1, "from": "a@b.com", "subject": "Hi", "date": "2026-01-01", "body": "", "account": "", "uid": 1, "recommendation": None}],
            page=1, total_pages=1, total_emails=1, content=""
        )
        mock_service.current_page.return_value = mock_result
        mock_service.to_dict.return_value = state.mail_engine

        req = DummyRequest("", query_params={"session_id": "s1"})
        with patch("src.gateway.routes.mail.MailService", return_value=mock_service):
            resp = mail_get(req, page=0)

        self.assertEqual(resp["total_emails"], 1)
        self.assertEqual(resp["emails"][0]["subject"], "Hi")
        self.assertEqual(resp["page"], 1)

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.gateway.routes.mail.save_session")
    def test_mail_analyze_returns_updated_page(self, save_session, load_session, _jwt):
        state = SessionState(session_id="s1", user_id="u1")
        state.mail_engine = {"inbox": [{"uid": 1, "subject": "Hi"}], "page": 0, "page_size": 20, "account": ""}
        load_session.return_value = state

        from src.gateway.routes.mail import mail_analyze, AnalyzeRequest
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_result = MagicMock(
            emails=[{"index": 1, "subject": "Hi", "summary": "Short summary", "recommended_todo": "Review"}],
            page=1, total_pages=1, total_emails=1, content=""
        )
        mock_service.analyze.return_value = mock_result
        mock_service.to_dict.return_value = state.mail_engine

        req = DummyRequest("", query_params={"session_id": "s1"})
        with patch("src.gateway.routes.mail.MailService", return_value=mock_service):
            resp = mail_analyze(req, AnalyzeRequest(indices=[1], preferences="prefer reply"))

        self.assertEqual(resp["emails"][0]["summary"], "Short summary")
        mock_service.analyze.assert_called_once_with(indices=[1], preferences="prefer reply")

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.gateway.routes.mail.save_session")
    def test_mail_feedback_records_verdict(self, save_session, load_session, _jwt):
        state = SessionState(session_id="s1", user_id="u1")
        state.mail_engine = {"inbox": [{"uid": 1, "subject": "Hi"}], "page": 0, "page_size": 20, "account": ""}
        load_session.return_value = state

        from src.gateway.routes.mail import mail_feedback, FeedbackRequest
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_service.to_dict.return_value = state.mail_engine

        req = DummyRequest("", query_params={"session_id": "s1"})
        with patch("src.gateway.routes.mail.MailService", return_value=mock_service):
            resp = mail_feedback(req, FeedbackRequest(index=1, verdict="good", text="good match"))

        self.assertEqual(resp["status"], "ok")
        mock_service.record_feedback.assert_called_once_with(1, "good", "good match")

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    def test_mail_get_no_engine_raises_404(self, load_session, _jwt):
        from fastapi import HTTPException
        from src.gateway.routes.mail import mail_get
        state = SessionState(session_id="s1", user_id="u1")
        load_session.return_value = state

        req = DummyRequest("", query_params={"session_id": "s1"})
        with self.assertRaises(HTTPException) as raised:
            mail_get(req, page=0)

        self.assertEqual(raised.exception.status_code, 404)

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.gateway.routes.mail.save_session")
    def test_mail_read_marks_message_read(self, save_session, load_session, _jwt):
        state = SessionState(session_id="s1", user_id="u1")
        state.mail_engine = {"inbox": [{"uid": 1, "subject": "Hi"}], "page": 0, "page_size": 20, "account": ""}
        load_session.return_value = state

        from src.gateway.routes.mail import mail_read
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_service.read.return_value = MagicMock(
            index=1,
            from_="a@b.com",
            subject="Hi",
            date="2026-01-01",
            body="Hello",
            account="Personal",
            uid=1,
            recommendation="review",
            summary="Summary",
            recommended_todo="Todo",
        )
        mock_service.to_dict.return_value = state.mail_engine

        req = DummyRequest("", query_params={"session_id": "s1"})
        with patch("src.gateway.routes.mail.MailService", return_value=mock_service):
            resp = mail_read(req, 1)

        self.assertEqual(resp["subject"], "Hi")
        mock_service.mark_read.assert_called_once_with(1)

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    def test_mail_get_missing_session_raises_400(self, load_session, _jwt):
        from fastapi import HTTPException
        from src.gateway.routes.mail import mail_get
        req = DummyRequest("")
        with self.assertRaises(HTTPException) as raised:
            mail_get(req, page=0)
        self.assertEqual(raised.exception.status_code, 400)


class SearchConfigEndpointTests(unittest.IsolatedAsyncioTestCase):
    @patch("src.gateway.routes.auth.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.auth._auth_service.get_search_provider", return_value="duckduckgo")
    async def test_get_search_config_returns_provider_options(self, get_search_provider, _jwt):
        from src.gateway.routes.auth import get_search_config

        req = DummyRequest("")
        resp = await get_search_config(req)

        self.assertEqual(resp.status_code, 200)
        body = resp.body.decode()
        self.assertIn('"search_provider":"duckduckgo"', body)
        self.assertIn('"id":"duckduckgo"', body)
        get_search_provider.assert_called_once_with("u1")

    @patch("src.gateway.routes.auth.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.auth._auth_service.update_search_provider", return_value="searx")
    async def test_update_search_config_saves_provider(self, update_search_provider, _jwt):
        from src.gateway.routes.auth import update_search_config

        req = DummyRequest('{"search_provider":"searx"}')
        resp = await update_search_config(req)

        self.assertEqual(resp.status_code, 200)
        body = resp.body.decode()
        self.assertIn('"search_provider":"searx"', body)
        update_search_provider.assert_called_once_with("u1", "searx")


class SearchEndpointTests(unittest.TestCase):
    @patch("src.gateway.routes.search.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.search._auth_service.get_search_provider", return_value="searx")
    @patch("src.gateway.routes.search._search_service.search")
    def test_search_uses_saved_provider(self, service_search, get_search_provider, _jwt):
        from src.gateway.routes.search import api_search, SearchRequest

        service_search.return_value = {
            "answer": "answer",
            "results": [{"title": "Result", "url": "https://example.com", "snippet": "snippet"}],
        }
        req = DummyRequest("")

        resp = api_search(SearchRequest(query="backend search"), req)

        self.assertEqual(resp.answer, "answer")
        get_search_provider.assert_called_once_with("u1")
        service_search.assert_called_once_with("backend search", provider_name="searx", skip_answer=False)


if __name__ == "__main__":
    unittest.main()
