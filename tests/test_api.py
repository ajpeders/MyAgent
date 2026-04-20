import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request

import server.__main__ as server_module
from core.session_store import SessionState


class DummyRequest:
    def __init__(self, body_json: str, headers: dict | None = None, query_params: dict | None = None):
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


class ApiTests(unittest.IsolatedAsyncioTestCase):
    @patch("server.__main__.dispatch_session")
    async def test_chat_without_session_is_stateless(self, dispatch_session):
        dispatch_session.return_value = [
            {"type": "answer", "content": "4", "agent": "answer"},
        ]

        req = DummyRequest('{"prompt":"what is 2 + 2?","confirm":false}')
        response = await server_module.chat(req)

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].type, "answer")
        self.assertEqual(response[0].content, "4")
        state = dispatch_session.call_args.args[0]
        self.assertEqual(state.session_id, "_stateless")

    @patch("server.__main__.save_session")
    @patch("server.__main__.load_session")
    @patch("server.__main__.dispatch_session")
    async def test_chat_with_session_loads_and_saves_state(self, dispatch_session, load_session, save_session):
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

        req = DummyRequest(
            '{"prompt":"check email","model":"test-model","session_id":"mail"}',
            headers={"X-User-ID": "test-user"},
            query_params={"session_id": "mail"},
        )
        resp = await server_module.chat(req)

        self.assertEqual(resp[0].emails, [{"index": 1, "subject": "Hello"}])
        self.assertEqual(resp[0].page, 1)
        load_session.assert_called_once_with("mail", user_id="test-user")
        save_session.assert_called_once_with(state)

    def test_health(self):
        self.assertEqual(server_module.health(), {"status": "ok"})

    @patch("server.__main__.dispatch_session", side_effect=RuntimeError("unexpected EOF"))
    async def test_chat_backend_failure_returns_502(self, _dispatch_session):
        req = DummyRequest('{"prompt":"check email","confirm":false}')
        with self.assertRaises(server_module.HTTPException) as raised:
            await server_module.chat(req)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("unexpected EOF", raised.exception.detail)


class ApiMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_key_required_for_api_routes(self):
        from types import SimpleNamespace

        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/chat"),
            headers={},
            query_params={},
        )
        call_next = AsyncMock()

        with patch("server.__main__.API_KEY", "secret"):
            response = await server_module.require_api_key(request, call_next)

        self.assertEqual(response.status_code, 401)
        self.assertFalse(call_next.called)

    async def test_api_key_allows_non_api_routes(self):
        from types import SimpleNamespace

        request = SimpleNamespace(
            url=SimpleNamespace(path="/health"),
            headers={},
            query_params={},
        )
        call_next = AsyncMock(return_value="ok")

        with patch("server.__main__.API_KEY", "secret"):
            response = await server_module.require_api_key(request, call_next)

        self.assertEqual(response, "ok")
        self.assertTrue(call_next.called)


class MailEndpointTests(unittest.TestCase):
    def _state_with_inbox(self, emails: list[dict]) -> SessionState:
        from core.mail_engine import MailEngine
        engine = MailEngine(model="test")
        engine.inbox = emails
        state = SessionState(session_id="s1", user_id="u1")
        state.mail_engine = engine.to_dict()
        return state

    @patch("server.__main__.load_session")
    def test_mail_get_returns_inbox_page(self, load_session):
        emails = [{"uid": 1, "from": "a@b.com", "subject": "Hi", "date": "2026-01-01", "body": "", "account": ""}]
        load_session.return_value = self._state_with_inbox(emails)

        req = DummyRequest("", headers={"X-User-ID": "u1"}, query_params={"session_id": "s1"})
        resp = server_module.mail_get(req, page=0)

        self.assertEqual(resp.total_emails, 1)
        self.assertEqual(resp.emails[0]["subject"], "Hi")
        self.assertEqual(resp.page, 1)

    @patch("server.__main__.load_session")
    def test_mail_get_no_engine_raises_404(self, load_session):
        state = SessionState(session_id="s1", user_id="u1")
        load_session.return_value = state

        req = DummyRequest("", headers={"X-User-ID": "u1"}, query_params={"session_id": "s1"})
        with self.assertRaises(server_module.HTTPException) as raised:
            server_module.mail_get(req, page=0)

        self.assertEqual(raised.exception.status_code, 404)

    @patch("server.__main__.load_session")
    def test_mail_get_missing_session_raises_400(self, load_session):
        req = DummyRequest("", headers={"X-User-ID": "u1"})
        with self.assertRaises(server_module.HTTPException) as raised:
            server_module.mail_get(req, page=0)
        self.assertEqual(raised.exception.status_code, 400)

    @patch("server.__main__.save_session")
    @patch("server.__main__.load_session")
    def test_mail_fetch_populates_session(self, load_session, save_session):
        from core.mail_engine import MailEngine
        state = SessionState(session_id="s1", user_id="u1")
        load_session.return_value = state
        fake_emails = [{"uid": 2, "from": "x@y.com", "subject": "Test", "date": "2026-01-02", "body": "", "account": ""}]

        with patch("core.mail_engine.mail_refresh"), \
             patch("core.mail_engine.mail_read_emails", return_value=fake_emails), \
             patch("core.mail_engine.default_adapter") as llm:
            llm.complete.return_value = '{"recommendations": []}'
            req = DummyRequest("", headers={"X-User-ID": "u1"}, query_params={"session_id": "s1"})
            resp = server_module.mail_fetch(req, server_module.FetchRequest())

        self.assertEqual(resp.total_emails, 1)
        self.assertEqual(resp.emails[0]["subject"], "Test")
        save_session.assert_called_once_with(state)
        self.assertIsNotNone(state.mail_engine)

    @patch("server.__main__.save_session")
    @patch("server.__main__.load_session")
    def test_mail_move_delegates_to_engine(self, load_session, save_session):
        emails = [{"uid": 10, "from": "a@b.com", "subject": "Hi", "date": "2026-01-01", "body": "", "account": "Gmail"}]
        state = self._state_with_inbox(emails)
        load_session.return_value = state

        with patch("core.mail_engine.mail_move_by_uids", return_value=1):
            req = DummyRequest("", headers={"X-User-ID": "u1"}, query_params={"session_id": "s1"})
            resp = server_module.mail_move(req, server_module.MoveRequest(indices=[1], folder="Trash"))

        self.assertEqual(resp["folder"], "Trash")
        self.assertIn("message", resp)
        save_session.assert_called_once()


if __name__ == "__main__":
    unittest.main()