"""Mail dispatcher — IMAP-only mail actions."""
from __future__ import annotations

from src.core.config import IMAP_ACCOUNTS


def _use_imap(imap_accounts: list[dict] | None = None) -> bool:
    return bool(imap_accounts or IMAP_ACCOUNTS)


def _require_imap(imap_accounts: list[dict] | None = None) -> None:
    if not _use_imap(imap_accounts):
        raise NotImplementedError("Mail actions require IMAP accounts")


def fetch_mailboxes(
    account_name: str = "",
    exclude: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[str]:
    _require_imap(imap_accounts)
    from .mail_imap import fetch_mailboxes as impl
    return impl(account_name=account_name, exclude=exclude, imap_accounts=imap_accounts)


def read_emails(
    count: int = 10,
    unread_only: bool = False,
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[dict]:
    _require_imap(imap_accounts)
    from .mail_imap import read_emails as impl
    return impl(
        count=count,
        unread_only=unread_only,
        mailbox=mailbox,
        account_name=account_name,
        imap_accounts=imap_accounts,
    )


def read_all_emails(
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[dict]:
    _require_imap(imap_accounts)
    from .mail_imap import read_all_emails as impl
    return impl(mailbox=mailbox, account_name=account_name, imap_accounts=imap_accounts)


def fetch_by_date(
    since: str,
    before: str,
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[dict]:
    _require_imap(imap_accounts)
    from .mail_imap import fetch_by_date as impl
    return impl(
        since=since,
        before=before,
        mailbox=mailbox,
        account_name=account_name,
        imap_accounts=imap_accounts,
    )


def create_folder(
    folder_name: str,
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> bool:
    _require_imap(imap_accounts)
    from .mail_imap import create_folder as impl
    return impl(folder_name=folder_name, account_name=account_name, imap_accounts=imap_accounts)


def move_emails(
    filter_from: str = "",
    filter_subject: str = "",
    folder: str = "Trash",
    mailbox: str = "INBOX",
    account_name: str = "",
    inbox: list[dict] | None = None,
    imap_accounts: list[dict] | None = None,
) -> int:
    _require_imap(imap_accounts)
    from .mail_imap import move_emails as impl
    return impl(
        filter_from=filter_from,
        filter_subject=filter_subject,
        folder=folder,
        mailbox=mailbox,
        account_name=account_name,
        inbox=inbox,
        imap_accounts=imap_accounts,
    )


def move_by_uids(
    uids: list[int],
    folder: str = "Trash",
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> int:
    _require_imap(imap_accounts)
    from .mail_imap import move_by_uids as impl
    return impl(
        uids=uids,
        folder=folder,
        mailbox=mailbox,
        account_name=account_name,
        imap_accounts=imap_accounts,
    )


def mark_read_by_uids(
    uids: list[int],
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> int:
    _require_imap(imap_accounts)
    from .mail_imap import mark_read_by_uids as impl
    return impl(
        uids=uids,
        mailbox=mailbox,
        account_name=account_name,
        imap_accounts=imap_accounts,
    )


def refresh_mail(imap_accounts: list[dict] | None = None) -> None:
    _require_imap(imap_accounts)
    from .mail_imap import refresh_mail as impl
    return impl()


def email_matches(email: dict, filter_from: str, filter_subject: str) -> bool:
    from .mail_imap import email_matches as impl
    return impl(email, filter_from, filter_subject)


def emails_to_text(emails: list[dict]) -> str:
    from .mail_imap import emails_to_text as impl
    return impl(emails)


MAIL_BACKEND = "imap"
