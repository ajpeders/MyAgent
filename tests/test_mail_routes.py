"""Tests for mail API routes: dev-seed, fetch-only, and by-date."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from src.gateway.routes.mail import (
    FetchRequest,
    mail_by_date,
    mail_dev_seed,
    mail_fetch_only,
)
from src.gateway.session import SessionState


class DummyRequest:
    def __init__(self, headers: dict | None = None, query_params: dict | None = None):
        self._headers = headers or {}
        self._query_params = query_params or {}

    @property
    def headers(self):
        return MagicMock(get=lambda key, default=None: self._headers.get(key, default))

    @property
    def query_params(self):
        return MagicMock(get=lambda key, default=None: self._query_params.get(key, default))


def _make_request(session_id: str = "test-session") -> DummyRequest:
    return DummyRequest(query_params={"session_id": session_id})


def _base_patches():
    """Return common patches for jwt_required, get_session_id, load_session, save_session."""
    return {
        "jwt": patch(
            "src.gateway.routes.mail.jwt_required",
            return_value={"user_id": "test-user", "enc_key": "test-key"},
        ),
        "session_id": patch(
            "src.gateway.routes.mail.get_session_id",
            return_value="test-session",
        ),
        "load": patch(
            "src.gateway.routes.mail.load_session",
            return_value=SessionState(session_id="test-session", user_id="test-user"),
        ),
        "save": patch("src.gateway.routes.mail.save_session"),
    }


class TestDevSeed(unittest.TestCase):
    def test_dev_seed_returns_fake_emails(self):
        patches = _base_patches()
        with patches["jwt"], patches["session_id"], patches["load"], patches["save"]:
            req = _make_request()
            resp = mail_dev_seed(req)

        self.assertIn("emails", resp)
        self.assertEqual(len(resp["emails"]), 10)

        first = resp["emails"][0]
        self.assertIn("from", first)
        self.assertIn("subject", first)
        self.assertIn("date", first)
        self.assertIn("account", first)


class TestFetchOnly(unittest.TestCase):
    def test_fetch_only_without_accounts_raises_400(self):
        patches = _base_patches()
        state = SessionState(session_id="test-session", user_id="test-user")
        state.imap_accounts = []
        patches["load"] = patch(
            "src.gateway.routes.mail.load_session", return_value=state
        )

        with (
            patches["jwt"],
            patches["session_id"],
            patches["load"],
            patches["save"],
            patch("src.gateway.routes.mail.IMAP_ACCOUNTS", []),
        ):
            req = _make_request()
            with self.assertRaises(HTTPException) as ctx:
                mail_fetch_only(req, FetchRequest())
            self.assertEqual(ctx.exception.status_code, 400)

    def test_fetch_only_calls_service_without_analyze(self):
        patches = _base_patches()
        state = SessionState(session_id="test-session", user_id="test-user")
        state.imap_accounts = [{"host": "imap.example.com"}]
        patches["load"] = patch(
            "src.gateway.routes.mail.load_session", return_value=state
        )

        mock_service = MagicMock()
        mock_result = MagicMock(
            emails=[], page=1, total_pages=1, total_emails=0, content=""
        )
        mock_service.fetch.return_value = mock_result
        mock_service.to_dict.return_value = {}

        with (
            patches["jwt"],
            patches["session_id"],
            patches["load"],
            patches["save"],
            patch("src.gateway.routes.mail.MailService", return_value=mock_service),
        ):
            req = _make_request()
            mail_fetch_only(req, FetchRequest(count=5))

        mock_service.fetch.assert_called_once()
        call_kwargs = mock_service.fetch.call_args
        self.assertEqual(call_kwargs.kwargs.get("analyze") or call_kwargs[1].get("analyze"), False)
        # Verify count=5 was passed
        self.assertEqual(call_kwargs.kwargs.get("count") or call_kwargs[1].get("count"), 5)


class TestByDate(unittest.TestCase):
    def test_by_date_with_single_date(self):
        patches = _base_patches()

        with (
            patches["jwt"],
            patches["session_id"],
            patches["load"],
            patches["save"],
            patch("src.gateway.routes.mail.fetch_by_date", create=True) as mock_fetch,
        ):
            # The route imports fetch_by_date inside the function body,
            # so we patch at the source module level.
            pass

        # Need to patch the import inside the function
        patches = _base_patches()
        mock_fetch_by_date = MagicMock(return_value=[])

        with (
            patches["jwt"],
            patches["session_id"],
            patches["load"],
            patches["save"],
            patch(
                "src.core.actions.mail_imap.fetch_by_date", mock_fetch_by_date
            ),
        ):
            req = _make_request()
            resp = mail_by_date(req, date="2026-04-25")

        mock_fetch_by_date.assert_called_once()
        call_kwargs = mock_fetch_by_date.call_args
        self.assertEqual(call_kwargs.kwargs["since"], "2026-04-25")
        self.assertEqual(call_kwargs.kwargs["before"], "2026-04-26")
        self.assertEqual(resp, {"emails": []})

    def test_by_date_without_params_raises_400(self):
        patches = _base_patches()

        with (
            patches["jwt"],
            patches["session_id"],
            patches["load"],
            patches["save"],
        ):
            req = _make_request()
            with self.assertRaises(HTTPException) as ctx:
                mail_by_date(req)
            self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
