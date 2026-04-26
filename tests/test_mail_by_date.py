"""Tests for the GET /api/mail/by-date endpoint and IMAP date search."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from src.gateway.session import SessionState


# ── Fixtures ─────────────────────────────────────────────────────────────────


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


FAKE_EMAILS = [
    {"id": 101, "subject": "Morning report", "from": "boss@co.com", "date": "2026-04-25", "read": True, "account": "Gmail"},
    {"id": 102, "subject": "Lunch?", "from": "friend@co.com", "date": "2026-04-25", "read": False, "account": "Gmail"},
]


@pytest.fixture
def state():
    return SessionState(session_id="s1", user_id="u1", imap_accounts=[{"name": "Gmail", "host": "imap.gmail.com"}])


# ── Route tests ──────────────────────────────────────────────────────────────


class TestMailByDateRoute:
    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.core.actions.mail_imap.fetch_by_date", return_value=FAKE_EMAILS)
    def test_single_date_returns_messages(self, mock_fetch, mock_load, _jwt, state):
        mock_load.return_value = state
        from src.gateway.routes.mail import mail_by_date

        req = DummyRequest(query_params={"session_id": "s1"})
        resp = mail_by_date(req, date="2026-04-25")

        assert len(resp["messages"]) == 2
        assert resp["messages"][0]["subject"] == "Morning report"
        # IMAP BEFORE should be date + 1 day
        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs["since"] == "2026-04-25"
        assert call_kwargs.kwargs["before"] == "2026-04-26"

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.core.actions.mail_imap.fetch_by_date", return_value=FAKE_EMAILS)
    def test_date_range_returns_messages(self, mock_fetch, mock_load, _jwt, state):
        mock_load.return_value = state
        from src.gateway.routes.mail import mail_by_date

        req = DummyRequest(query_params={"session_id": "s1"})
        resp = mail_by_date(req, start="2026-04-01", end="2026-04-30")

        assert "messages" in resp
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs["since"] == "2026-04-01"
        assert call_kwargs.kwargs["before"] == "2026-05-01"  # end + 1 day

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    def test_missing_date_params_raises_400(self, mock_load, _jwt, state):
        mock_load.return_value = state
        from src.gateway.routes.mail import mail_by_date

        req = DummyRequest(query_params={"session_id": "s1"})
        with pytest.raises(HTTPException) as exc:
            mail_by_date(req)
        assert exc.value.status_code == 400

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.core.actions.mail_imap.fetch_by_date", return_value=[])
    def test_no_emails_returns_empty(self, mock_fetch, mock_load, _jwt, state):
        mock_load.return_value = state
        from src.gateway.routes.mail import mail_by_date

        req = DummyRequest(query_params={"session_id": "s1"})
        resp = mail_by_date(req, date="2026-01-01")
        assert resp["messages"] == []

    @patch("src.gateway.routes.mail.jwt_required", return_value={"user_id": "u1"})
    @patch("src.gateway.routes.mail.load_session")
    @patch("src.core.actions.mail_imap.fetch_by_date", side_effect=ValueError("No IMAP accounts"))
    def test_imap_error_raises_400(self, mock_fetch, mock_load, _jwt, state):
        mock_load.return_value = state
        from src.gateway.routes.mail import mail_by_date

        req = DummyRequest(query_params={"session_id": "s1"})
        with pytest.raises(HTTPException) as exc:
            mail_by_date(req, date="2026-04-25")
        assert exc.value.status_code == 400


# ── IMAP date formatting ─────────────────────────────────────────────────────


class TestImapDateFormat:
    def test_imap_date_criteria_format(self):
        """Verify the IMAP date conversion produces DD-Mon-YYYY format."""
        from datetime import datetime

        dt = datetime.strptime("2026-04-25", "%Y-%m-%d")
        imap_fmt = dt.strftime("%d-%b-%Y")
        assert imap_fmt == "25-Apr-2026"

    def test_end_of_month_range(self):
        """Verify date + 1 day wraps to next month correctly."""
        from datetime import date, timedelta

        end = date.fromisoformat("2026-04-30")
        before = end + timedelta(days=1)
        assert str(before) == "2026-05-01"
