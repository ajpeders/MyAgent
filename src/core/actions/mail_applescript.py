import subprocess

from src.core.config import TARGET_MAILBOX


def fetch_mailboxes(exclude: str = "") -> list[str]:
    script = """
    tell application "Mail"
        set output to ""
        repeat with mb in every mailbox
            try
                set mailboxPath to ((name of account of mb) & " / " & (name of mb))
            on error
                set mailboxPath to (name of mb)
            end try
            set output to output & mailboxPath & "\\n"
        end repeat
        return output
    end tell
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    mailboxes = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    if exclude:
        mailboxes = [mailbox for mailbox in mailboxes if mailbox != exclude]
    return mailboxes


def refresh_mail():
    script = """
    tell application "Mail"
        check for new mail
    end tell
    """
    subprocess.run(["osascript", "-e", script], capture_output=True, env={**__import__('os').environ, "TERM": "dumb"})


def read_emails(
    count: int = 10,
    unread_only: bool = False,
    mailbox: str = TARGET_MAILBOX,
    account_name: str = "",
) -> list[dict]:
    filter_clause = "whose read status is false" if unread_only else ""
    script = f"""
    tell application "Mail"
        set sourceMailbox to mailbox "{mailbox}"
        set allMsgs to (messages of sourceMailbox {filter_clause})
        set msgCount to count of allMsgs
        if msgCount > {count} then set msgCount to {count}
        set msgs to items 1 through msgCount of allMsgs
        set output to ""
        repeat with m in msgs
            set output to output & "SUBJECT: " & (subject of m) & "\\n"
            set output to output & "---\\n"
        end repeat
        return output
    end tell
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    emails = []
    for block in result.stdout.strip().split("---"):
        block = block.strip()
        if not block:
            continue
        email = {}
        for line in block.splitlines():
            if line.startswith("SUBJECT: "):
                email["subject"] = line[9:]
        if email:
            emails.append(email)
    return emails


def move_emails(
    filter_from: str = "",
    filter_subject: str = "",
    folder: str = "Archive",
    mailbox: str = TARGET_MAILBOX,
    account_name: str = "",
    inbox: list[dict] | None = None,
) -> int:
    conditions = []
    if filter_from:
        conditions.append(f'sender contains "{filter_from}"')
    if filter_subject:
        conditions.append(f'subject contains "{filter_subject}"')
    whose = f" whose {' and '.join(conditions)}" if conditions else ""
    script = f"""
    tell application "Mail"
        set targetMailbox to mailbox "{folder}"
        set sourceMailbox to mailbox "{mailbox}"
        set msgs to (messages of sourceMailbox{whose})
        repeat with m in msgs
            move m to targetMailbox
        end repeat
        return (count of msgs) as integer
    end tell
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def move_by_uids(
    uids: list[int],
    folder: str = "Trash",
    mailbox: str = TARGET_MAILBOX,
    account_name: str = "",
) -> int:
    """AppleScript fallback cannot safely address messages by IMAP UID."""
    raise NotImplementedError("AppleScript mail backend does not support UID-based moves")


def email_matches(email: dict, filter_from: str, filter_subject: str) -> bool:
    if filter_from and filter_from.lower() not in email.get("from", "").lower():
        return False
    if filter_subject and filter_subject.lower() not in email.get("subject", "").lower():
        return False
    return True


def emails_to_text(emails: list[dict]) -> str:
    return "\n---\n".join(
        f"SUBJECT: {e.get('subject', '')}"
        for e in emails
    )
