import email
import json
import re
from email.header import decode_header
from html.parser import HTMLParser

from imapclient import IMAPClient

from src.core.config import IMAP_ACCOUNTS


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML-to-text converter — strips tags, keeps text content."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        self._skip = tag in ("style", "script", "head")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        text = " ".join(self._parts)
        return re.sub(r'\s+', ' ', text).strip()


def _decode_header(value: str) -> str:
    """Decode an RFC 2047 encoded header into a plain string."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _get_account(
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> dict:
    """Return account config for the given name.

    Prefers imap_accounts (decrypted, from the session) over the config-based
    IMAP_ACCOUNTS fallback.
    """
    sources = imap_accounts if imap_accounts is not None else IMAP_ACCOUNTS
    if not sources:
        raise ValueError("No IMAP accounts available")
    if not account_name:
        return sources[0]
    for acct in sources:
        if acct.get("name") == account_name:
            return acct
    raise ValueError(f"IMAP account '{account_name}' not found")


def _connect(account: dict) -> IMAPClient:
    """Open an SSL connection and log in."""
    host = account["host"]
    port = account.get("port", 993)
    client = IMAPClient(host, port=port, ssl=True)
    client.login(account["user"], account["password"])
    return client


def fetch_mailboxes(
    account_name: str = "",
    exclude: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[str]:
    """List IMAP folders. If account_name is given, list that account only.
    Otherwise list all accounts with folders prefixed like 'Gmail / INBOX'."""
    sources = imap_accounts if imap_accounts is not None else IMAP_ACCOUNTS
    if account_name:
        accts = [_get_account(account_name, imap_accounts)]
    else:
        accts = sources
    result = []
    for acct in accts:
        client = _connect(acct)
        try:
            folders = client.list_folders()
            for _flags, _delimiter, folder_name in folders:
                if isinstance(folder_name, bytes):
                    folder_name = folder_name.decode("utf-8", errors="replace")
                if account_name:
                    result.append(folder_name)
                else:
                    result.append(f"{acct['name']} / {folder_name}")
        finally:
            client.logout()
    if exclude:
        result = [f for f in result if f != exclude]
    return result


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text by stripping tags."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _extract_body(raw_bytes: bytes, max_chars: int = 500) -> str:
    """Extract plain-text body from a raw email, truncated to max_chars.
    Falls back to stripping HTML if no text/plain part exists."""
    msg = email.message_from_bytes(raw_bytes)
    plain = ""
    html = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if content_type == "text/plain" and not plain:
                plain = text
            elif content_type == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text

    body = plain.strip() if plain else _html_to_text(html)
    if len(body) > max_chars:
        body = body[:max_chars] + "..."
    return body


def _fetch_from_account(
    acct: dict,
    count: int,
    unread_only: bool,
    mailbox: str,
) -> list[dict]:
    """Fetch emails from a single IMAP account."""
    client = _connect(acct)
    try:
        client.select_folder(mailbox, readonly=True)

        criteria = ["UNSEEN"] if unread_only else ["ALL"]
        uids = client.search(criteria)
        uids = uids[-count:]

        if not uids:
            return []

        raw_messages = client.fetch(uids, ["ENVELOPE", "RFC822"])
        emails_out = []
        for uid in uids:
            data = raw_messages.get(uid, {})
            envelope = data.get(b"ENVELOPE")
            raw_body = data.get(b"RFC822", b"")
            body = _extract_body(raw_body) if raw_body else ""

            if envelope:
                subject = _decode_header(envelope.subject.decode("utf-8", errors="replace")
                                         if isinstance(envelope.subject, bytes)
                                         else (envelope.subject or ""))
                from_addr = ""
                if envelope.from_:
                    addr = envelope.from_[0]
                    name = (addr.name.decode("utf-8", errors="replace")
                            if isinstance(addr.name, bytes) else (addr.name or ""))
                    mailbox_part = (addr.mailbox.decode("utf-8", errors="replace")
                                    if isinstance(addr.mailbox, bytes) else (addr.mailbox or ""))
                    host_part = (addr.host.decode("utf-8", errors="replace")
                                 if isinstance(addr.host, bytes) else (addr.host or ""))
                    from_addr = f"{name} <{mailbox_part}@{host_part}>" if name else f"{mailbox_part}@{host_part}"
                date_str = str(envelope.date) if envelope.date else ""
                emails_out.append({
                    "uid": uid,
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "body": body,
                    "account": acct["name"],
                })
            else:
                msg = email.message_from_bytes(raw_body or b"")
                emails_out.append({
                    "uid": uid,
                    "subject": _decode_header(msg.get("Subject", "")),
                    "from": msg.get("From", ""),
                    "date": msg.get("Date", ""),
                    "body": body,
                    "account": acct["name"],
                })
        return emails_out
    finally:
        client.logout()


def read_emails(
    count: int = 10,
    unread_only: bool = False,
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[dict]:
    """Fetch emails from the given mailbox.

    If account_name is empty and multiple accounts exist, fetches from all.
    imap_accounts are decrypted session credentials; falls back to config IMAP_ACCOUNTS.
    """
    sources = imap_accounts if imap_accounts is not None else IMAP_ACCOUNTS
    if account_name or len(sources) == 1:
        acct = _get_account(account_name, imap_accounts)
        return _fetch_from_account(acct, count, unread_only, mailbox)

    all_emails = []
    for acct in sources:
        try:
            all_emails.extend(_fetch_from_account(acct, count, unread_only, mailbox))
        except Exception as e:
            print(f"[mail] warning: could not fetch from {acct.get('name', '?')}: {e}", flush=True)
    return all_emails


def read_all_emails(
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[dict]:
    """Fetch ALL emails from the given mailbox (no count limit)."""
    acct = _get_account(account_name, imap_accounts)
    return _fetch_all_from_account(acct, mailbox)


def _fetch_all_from_account(acct: dict, mailbox: str) -> list[dict]:
    """Fetch all emails from a single account's mailbox (no limit)."""
    client = _connect(acct)
    try:
        client.select_folder(mailbox, readonly=True)
        uids = client.search(["ALL"])

        if not uids:
            return []

        raw_messages = client.fetch(uids, ["ENVELOPE", "RFC822"])
        emails_out = []
        for uid in uids:
            data = raw_messages.get(uid, {})
            envelope = data.get(b"ENVELOPE")
            raw_body = data.get(b"RFC822", b"")
            body = _extract_body(raw_body) if raw_body else ""

            if envelope:
                subject = _decode_header(envelope.subject.decode("utf-8", errors="replace")
                                         if isinstance(envelope.subject, bytes)
                                         else (envelope.subject or ""))
                from_addr = ""
                if envelope.from_:
                    addr = envelope.from_[0]
                    name = (addr.name.decode("utf-8", errors="replace")
                            if isinstance(addr.name, bytes) else (addr.name or ""))
                    mailbox_part = (addr.mailbox.decode("utf-8", errors="replace")
                                    if isinstance(addr.mailbox, bytes) else (addr.mailbox or ""))
                    host_part = (addr.host.decode("utf-8", errors="replace")
                                 if isinstance(addr.host, bytes) else (addr.host or ""))
                    from_addr = f"{name} <{mailbox_part}@{host_part}>" if name else f"{mailbox_part}@{host_part}"
                date_str = str(envelope.date) if envelope.date else ""
                emails_out.append({
                    "uid": uid,
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "body": body,
                    "account": acct["name"],
                })
            else:
                msg = email.message_from_bytes(raw_body or b"")
                emails_out.append({
                    "uid": uid,
                    "subject": _decode_header(msg.get("Subject", "")),
                    "from": msg.get("From", ""),
                    "date": msg.get("Date", ""),
                    "body": body,
                    "account": acct["name"],
                })
        return emails_out
    finally:
        client.logout()


def create_folder(
    folder_name: str,
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> bool:
    """Create a new IMAP folder. Returns True on success, False on failure."""
    acct = _get_account(account_name, imap_accounts)
    client = _connect(acct)
    try:
        client.create_folder(folder_name)
        return True
    except Exception as e:
        print(f"[mail] create_folder failed: {e}", flush=True)
        return False
    finally:
        client.logout()


def _resolve_folder(client: IMAPClient, folder: str) -> str:
    """Resolve a generic folder name to the actual IMAP folder path.
    E.g. 'Trash' → '[Gmail]/Trash' on Gmail, 'Trash' on Yahoo."""
    # Try exact match first
    folders = client.list_folders()
    folder_names = []
    for _flags, _delim, name in folders:
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        folder_names.append(name)

    if folder in folder_names:
        return folder

    # Search for a folder ending with the target name (e.g. [Gmail]/Trash)
    for name in folder_names:
        if name.endswith(f"/{folder}") or name.endswith(f"]/{folder}"):
            return name

    return folder  # fall back to original


def move_by_uids(
    uids: list[int],
    folder: str = "Trash",
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> int:
    """Move specific emails by UID to the given folder."""
    if not uids:
        return 0
    acct = _get_account(account_name, imap_accounts)
    client = _connect(acct)
    try:
        folder = _resolve_folder(client, folder)
        client.select_folder(mailbox)
        client.copy(uids, folder)
        client.add_flags(uids, [b"\\Deleted"])
        client.expunge(uids)
        return len(uids)
    finally:
        client.logout()


def move_emails(
    filter_from: str = "",
    filter_subject: str = "",
    folder: str = "Trash",
    mailbox: str = "INBOX",
    account_name: str = "",
    inbox: list[dict] | None = None,
    imap_accounts: list[dict] | None = None,
) -> int:
    """Move emails matching filters using UIDs from the inbox cache."""
    if inbox is not None:
        matched = [e for e in inbox if email_matches(e, filter_from, filter_subject)]
        uids = [e["uid"] for e in matched if "uid" in e]
        if not uids:
            return 0
        return move_by_uids(uids, folder, mailbox, account_name, imap_accounts)

    acct = _get_account(account_name, imap_accounts)
    client = _connect(acct)
    try:
        folder = _resolve_folder(client, folder)
        client.select_folder(mailbox)

        criteria = []
        if filter_from:
            criteria.extend(["FROM", _extract_email_addr(filter_from)])
        if filter_subject:
            criteria.extend(["SUBJECT", filter_subject])
        if not criteria:
            return 0

        uids = client.search(criteria)
        if not uids:
            return 0

        client.copy(uids, folder)
        client.add_flags(uids, [b"\\Deleted"])
        client.expunge(uids)
        return len(uids)
    finally:
        client.logout()


def fetch_by_date(
    since: str,
    before: str,
    mailbox: str = "INBOX",
    account_name: str = "",
    imap_accounts: list[dict] | None = None,
) -> list[dict]:
    """Fetch emails within a date range (inclusive).

    since/before are date strings in YYYY-MM-DD format.
    IMAP SINCE is inclusive, BEFORE is exclusive — caller should add 1 day to `before`.
    """
    from datetime import datetime

    since_dt = datetime.strptime(since, "%Y-%m-%d")
    before_dt = datetime.strptime(before, "%Y-%m-%d")
    # IMAP date format: DD-Mon-YYYY
    since_imap = since_dt.strftime("%d-%b-%Y")
    before_imap = before_dt.strftime("%d-%b-%Y")

    sources = imap_accounts if imap_accounts is not None else IMAP_ACCOUNTS
    if account_name or len(sources) == 1:
        acct = _get_account(account_name, imap_accounts)
        return _fetch_by_date_from_account(acct, since_imap, before_imap, mailbox)

    all_emails = []
    for acct in sources:
        try:
            all_emails.extend(_fetch_by_date_from_account(acct, since_imap, before_imap, mailbox))
        except Exception as e:
            print(f"[mail] warning: could not fetch from {acct.get('name', '?')}: {e}", flush=True)
    return all_emails


def _fetch_by_date_from_account(
    acct: dict, since_imap: str, before_imap: str, mailbox: str
) -> list[dict]:
    """Fetch emails from one account within an IMAP date range."""
    client = _connect(acct)
    try:
        client.select_folder(mailbox, readonly=True)
        criteria = ["SINCE", since_imap, "BEFORE", before_imap]
        uids = client.search(criteria)

        if not uids:
            return []

        raw_messages = client.fetch(uids, ["ENVELOPE", "FLAGS", "RFC822"])
        emails_out = []
        for uid in uids:
            data = raw_messages.get(uid, {})
            envelope = data.get(b"ENVELOPE")
            flags = data.get(b"FLAGS", ())
            raw_body = data.get(b"RFC822", b"")
            is_read = b"\\Seen" in flags

            if envelope:
                subject = _decode_header(
                    envelope.subject.decode("utf-8", errors="replace")
                    if isinstance(envelope.subject, bytes)
                    else (envelope.subject or "")
                )
                from_addr = ""
                if envelope.from_:
                    addr = envelope.from_[0]
                    name = (addr.name.decode("utf-8", errors="replace")
                            if isinstance(addr.name, bytes) else (addr.name or ""))
                    mailbox_part = (addr.mailbox.decode("utf-8", errors="replace")
                                    if isinstance(addr.mailbox, bytes) else (addr.mailbox or ""))
                    host_part = (addr.host.decode("utf-8", errors="replace")
                                 if isinstance(addr.host, bytes) else (addr.host or ""))
                    from_addr = f"{name} <{mailbox_part}@{host_part}>" if name else f"{mailbox_part}@{host_part}"
                date_str = str(envelope.date) if envelope.date else ""
            else:
                msg = email.message_from_bytes(raw_body or b"")
                subject = _decode_header(msg.get("Subject", ""))
                from_addr = msg.get("From", "")
                date_str = msg.get("Date", "")

            emails_out.append({
                "id": uid,
                "subject": subject,
                "from": from_addr,
                "date": date_str,
                "read": is_read,
                "account": acct["name"],
            })
        return emails_out
    finally:
        client.logout()


def refresh_mail():
    """No-op for IMAP — connections are always live."""
    pass


def _extract_email_addr(s: str) -> str:
    """Extract bare email address from 'Name <addr>' or return as-is."""
    if "<" in s and ">" in s:
        return s[s.index("<") + 1:s.index(">")]
    return s


def email_matches(email_dict: dict, filter_from: str, filter_subject: str) -> bool:
    """Check whether an email dict matches the given from/subject filters."""
    if filter_from:
        from_field = email_dict.get("from", "").lower()
        filter_addr = _extract_email_addr(filter_from).lower()
        if filter_addr not in from_field:
            return False
    if filter_subject and filter_subject.lower() not in email_dict.get("subject", "").lower():
        return False
    return True


def emails_to_text(emails: list[dict]) -> str:
    """Format a list of email dicts into readable text for the LLM."""
    lines = []
    for i, e in enumerate(emails, 1):
        account = e.get("account", "")
        account_label = f"   ACCOUNT: {account}\n" if account else ""
        entry = (
            f"{i}. FROM: {e.get('from', 'unknown')}\n"
            f"   SUBJECT: {e.get('subject', '(no subject)')}\n"
            f"   DATE: {e.get('date', '')}\n"
            f"{account_label}"
        )
        body = e.get("body", "")
        if body:
            entry += f"   BODY: {body}"
        lines.append(entry.rstrip())
    return "\n---\n".join(lines)
