"""Mail dispatcher — routes to IMAP (primary) or AppleScript (fallback).

IMAP is used when IMAP_ACCOUNTS is configured in .env.
AppleScript is the fallback for macOS with Mail.app.
"""
from core.config import IMAP_ACCOUNTS

if IMAP_ACCOUNTS:
    from .mail_imap import (
        fetch_mailboxes,
        read_emails,
        read_all_emails,
        create_folder,
        move_emails,
        move_by_uids,
        refresh_mail,
        email_matches,
        emails_to_text,
    )
    MAIL_BACKEND = "imap"
else:
    from .mail_applescript import (
        fetch_mailboxes,
        read_emails,
        move_emails,
        move_by_uids,
        refresh_mail,
        email_matches,
        emails_to_text,
    )
    MAIL_BACKEND = "applescript"
