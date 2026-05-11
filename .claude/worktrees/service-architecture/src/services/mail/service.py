"""Mail service — IMAP fetch, email display, move/delete. Owns email_cache table."""
from dataclasses import dataclass

from gateway.session import SessionState
from services.mail.errors import (
    EmailNotFoundError,
    FolderResolutionError,
    ImapConnectionError,
    MailServiceError,
    NoActiveSessionError,
)


@dataclass
class MailListResult:
    emails: list[dict]
    page: int
    total_pages: int
    total_emails: int
    content: str


@dataclass
class EmailDetail:
    index: int
    from_: str
    subject: str
    date: str
    body: str
    account: str
    uid: any
    recommendation: str


class MailService:
    """Thin wrapper over MailEngine with session state bridging."""

    def __init__(self, session: SessionState):
        self._session = session
        self._engine: any = None
        if session.mail_engine:
            from src.core.mail_engine import MailEngine

            self._engine = MailEngine.from_dict(session.mail_engine, imap_accounts=session.imap_accounts)

    def _require_engine(self):
        if not self._engine:
            raise NoActiveSessionError("No active mail session — call fetch first")
        return self._engine

    def fetch(self, count: int = 0, unread_only: bool = False, account: str = "") -> MailListResult:
        from src.core.mail_engine import MailEngine
        from src.core.config import MAIL_SUMMARY_COUNT, IMAP_ACCOUNTS

        if not self._engine:
            self._engine = MailEngine(model="", imap_accounts=self._session.imap_accounts)

        try:
            self._engine.fetch(count=count or MAIL_SUMMARY_COUNT, unread_only=unread_only, account=account)
        except ValueError as e:
            raise ImapConnectionError(str(e))

        result = self._engine._mail_list_result()
        return MailListResult(
            emails=result["emails"],
            page=result["page"],
            total_pages=result["total_pages"],
            total_emails=result["total_emails"],
            content=result["content"],
        )

    def move(self, indices: list[int], folder: str) -> str:
        engine = self._require_engine()
        from src.core.actions.action import Action, ActionType

        action = Action(type=ActionType.mail_move, indices=indices, folder=folder)
        message = engine.execute(action)
        return message

    def read(self, index: int) -> EmailDetail:
        engine = self._require_engine()
        email = engine._email_for_index(index)
        if email is None:
            raise EmailNotFoundError(f"No email at index {index}")
        return EmailDetail(
            index=index,
            from_=email.get("from", ""),
            subject=email.get("subject", ""),
            date=email.get("date", ""),
            body=email.get("body", ""),
            account=email.get("account", ""),
            uid=email.get("uid"),
            recommendation=email.get("recommendation", ""),
        )

    def handle(self, prompt: str, interactive: bool = False) -> list[dict]:
        engine = self._require_engine()
        return engine.handle(prompt, interactive=interactive)

    def to_dict(self) -> dict | None:
        return self._engine.to_dict() if self._engine else None