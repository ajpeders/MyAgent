"""Mail service — IMAP fetch, email display, move/delete. Owns email_cache table."""
import json
import time
from dataclasses import dataclass

from src.core.config import DEFAULT_MODEL
from src.core.crypto import decrypt_payload, encrypt_payload
from src.core.db import _connect
from src.core.config import TARGET_MAILBOX
from src.gateway.session import SessionState
from src.services.auth.store import UserStore
from src.services.mail.errors import (
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
    body_html: str
    account: str
    uid: int | str | None
    recommendation: str
    summary: str
    recommended_todo: str
    attachments: list[dict]


class MailService:
    """Thin wrapper over MailEngine with session state bridging."""

    def __init__(self, session: SessionState, enc_key: str = ""):
        self._session = session
        self._enc_key = enc_key
        self._engine: any = None
        self._model = self._load_model()
        if session.mail_engine:
            from src.core.mail_engine import MailEngine

            self._engine = MailEngine.from_dict(session.mail_engine, imap_accounts=session.imap_accounts)
            self._engine.model = self._model
        elif self._enc_key:
            self._engine = self._load_cached_engine()

    def _load_model(self) -> str:
        user = UserStore().get_user_by_id(self._session.user_id)
        if not user:
            return DEFAULT_MODEL
        return user.get("mail_model") or DEFAULT_MODEL

    def _load_preferences(self) -> str:
        user = UserStore().get_user_by_id(self._session.user_id)
        if not user:
            return ""
        return user.get("mail_preferences") or ""

    def _get_folder_list(self, account: str = "") -> list[str]:
        """Get the folder list for context in AI recommendations."""
        from src.core.actions.mail_imap import fetch_mailboxes
        from src.core.config import IMAP_ACCOUNTS
        try:
            return fetch_mailboxes(account_name=account, imap_accounts=self._session.imap_accounts or IMAP_ACCOUNTS)
        except Exception:
            return []

    def _restore_engine(self):
        if self._engine:
            return self._engine
        self._engine = self._load_persisted_engine() or self._load_cached_engine()
        return self._engine

    def _require_engine(self):
        self._restore_engine()
        if not self._engine:
            raise NoActiveSessionError("No active mail session — call fetch first")
        engine_model = self._load_model()
        self._engine.model = engine_model
        return self._engine

    def _cache_account_key(self) -> str:
        return "__default__"

    def _message_scope(self) -> tuple[str, str]:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT account_name, mailbox
                FROM email_sync_state
                WHERE user_id = ?
                ORDER BY last_synced_at DESC
                LIMIT 1
                """,
                (self._session.user_id,),
            ).fetchone()
            if row:
                return row[0], row[1]
            row = conn.execute(
                """
                SELECT account_name, mailbox
                FROM email_messages
                WHERE user_id = ?
                ORDER BY synced_at DESC, sort_rank ASC
                LIMIT 1
                """,
                (self._session.user_id,),
            ).fetchone()
            if row:
                return row[0], row[1]
            return "", TARGET_MAILBOX
        finally:
            conn.close()

    def _load_persisted_engine(self):
        from src.core.mail_engine import MailEngine

        if not self._enc_key:
            return None

        account_name, mailbox = self._message_scope()
        conn = _connect()
        if account_name:
            rows = conn.execute(
                """
                SELECT uid, uidvalidity, message_id, encrypted_blob
                FROM email_messages
                WHERE user_id = ? AND account_name = ? AND mailbox = ?
                ORDER BY synced_at DESC, sort_rank ASC
                """,
                (self._session.user_id, account_name, mailbox),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT uid, uidvalidity, message_id, encrypted_blob
                FROM email_messages
                WHERE user_id = ? AND mailbox = ?
                ORDER BY synced_at DESC, sort_rank ASC
                """,
                (self._session.user_id, mailbox),
            ).fetchall()
        conn.close()
        if not rows:
            return None

        inbox: list[dict] = []
        for uid, uidvalidity, message_id, blob in rows:
            try:
                if isinstance(blob, bytes):
                    blob = blob.decode()
                encrypted = json.loads(blob)
                payload = decrypt_payload(encrypted, self._enc_key)
                email = payload.get("email", {})
                email["uid"] = uid
                email["uidvalidity"] = uidvalidity or ""
                email["message_id"] = message_id or email.get("message_id", "")
                email["account"] = email.get("account", account_name)
                email["mailbox"] = email.get("mailbox", mailbox)
                inbox.append(email)
            except Exception:
                continue

        if not inbox:
            return None

        engine = MailEngine(model=self._model, imap_accounts=self._session.imap_accounts)
        engine.model = self._model
        engine.account = account_name
        engine.inbox = inbox
        return engine

    def _load_cached_engine(self):
        from src.core.mail_engine import MailEngine

        conn = _connect()
        row = conn.execute(
            "SELECT encrypted_blob FROM email_cache WHERE user_id = ? AND account_name = ? AND mailbox = ?",
            (self._session.user_id, self._cache_account_key(), "Inbox"),
        ).fetchone()
        conn.close()
        if not row:
            return None
        try:
            blob = row[0]
            if isinstance(blob, bytes):
                blob = blob.decode()
            encrypted = json.loads(blob)
            payload = decrypt_payload(encrypted, self._enc_key)
            engine = MailEngine.from_dict(payload["mail_engine"], imap_accounts=self._session.imap_accounts)
            engine.model = self._model
            return engine
        except Exception:
            return None

    def _save_messages(self, emails: list[dict]) -> None:
        if not self._enc_key:
            return
        account_name = self._engine.account or (emails[0].get("account", "") if emails else "")
        mailbox = emails[0].get("mailbox", TARGET_MAILBOX) if emails else TARGET_MAILBOX
        now = time.time()
        conn = _connect()
        try:
            for sort_rank, email in enumerate(emails):
                payload = {
                    "email": {
                        "id": email.get("id"),
                        "from": email.get("from", ""),
                        "subject": email.get("subject", ""),
                        "date": email.get("date", ""),
                        "body": email.get("body", ""),
                        "account": email.get("account", account_name),
                        "mailbox": email.get("mailbox", mailbox),
                        "read": bool(email.get("read", False)),
                        "recommendation": email.get("recommendation", ""),
                        "summary": email.get("summary", ""),
                        "recommended_todo": email.get("recommended_todo", ""),
                        "attachments": email.get("attachments", []),
                        "message_id": email.get("message_id", ""),
                        "uidvalidity": str(email.get("uidvalidity", "") or ""),
                        "analyzed_at": now,
                        "model": self._model,
                    }
                }
                encrypted = encrypt_payload(payload, self._enc_key)
                blob = json.dumps(encrypted).encode()
                conn.execute(
                    """
                    INSERT INTO email_messages (
                        user_id, account_name, mailbox, uid, uidvalidity, message_id,
                        sort_rank, synced_at, encrypted_blob, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, account_name, mailbox, uidvalidity, uid)
                    DO UPDATE SET
                        message_id = excluded.message_id,
                        sort_rank = excluded.sort_rank,
                        synced_at = excluded.synced_at,
                        encrypted_blob = excluded.encrypted_blob,
                        updated_at = excluded.updated_at
                    """,
                    (
                        self._session.user_id,
                        email.get("account", account_name),
                        email.get("mailbox", mailbox),
                        int(email.get("uid") or 0),
                        str(email.get("uidvalidity", "") or ""),
                        email.get("message_id", ""),
                        sort_rank,
                        now,
                        blob,
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO email_sync_state (user_id, account_name, mailbox, uidvalidity, last_synced_at, last_count, last_error)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(user_id, account_name, mailbox)
                DO UPDATE SET
                    uidvalidity = excluded.uidvalidity,
                    last_synced_at = excluded.last_synced_at,
                    last_count = excluded.last_count,
                    last_error = excluded.last_error
                """,
                (
                    self._session.user_id,
                    account_name,
                    mailbox,
                    str(emails[0].get("uidvalidity", "") or "") if emails else "",
                    now,
                    len(emails),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _persisted_metadata_for_scope(self, account_name: str = "", mailbox: str = TARGET_MAILBOX) -> tuple[dict[tuple[str, int], dict], dict[str, dict]]:
        """Load saved AI metadata for a mailbox, keyed by uid and message-id."""
        conn = _connect()
        try:
            if account_name:
                rows = conn.execute(
                    """
                    SELECT uid, uidvalidity, message_id, encrypted_blob
                    FROM email_messages
                    WHERE user_id = ? AND account_name = ? AND mailbox = ?
                    """,
                    (self._session.user_id, account_name, mailbox),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT uid, uidvalidity, message_id, encrypted_blob
                    FROM email_messages
                    WHERE user_id = ? AND mailbox = ?
                    """,
                    (self._session.user_id, mailbox),
                ).fetchall()
        finally:
            conn.close()

        by_uid: dict[tuple[str, int], dict] = {}
        by_message_id: dict[str, dict] = {}
        for uid, uidvalidity, message_id, blob in rows:
            try:
                if isinstance(blob, bytes):
                    blob = blob.decode()
                payload = decrypt_payload(json.loads(blob), self._enc_key)
                email = payload.get("email", {})
            except Exception:
                continue

            metadata = {
                "recommendation": self._engine.normalize_recommendation(email.get("recommendation", "")) if self._engine else email.get("recommendation", ""),
                "summary": email.get("summary", ""),
                "recommended_todo": email.get("recommended_todo", ""),
                "suggested_actions": email.get("suggested_actions", []),
            }
            if uid is not None:
                by_uid[(str(uidvalidity or ""), int(uid))] = metadata
            if message_id:
                by_message_id[message_id] = metadata
        return by_uid, by_message_id

    def _merge_persisted_metadata(self, emails: list[dict], account_name: str = "", mailbox: str = TARGET_MAILBOX) -> None:
        """Reapply saved AI metadata onto freshly fetched messages."""
        if not self._enc_key or not emails:
            return

        by_uid, by_message_id = self._persisted_metadata_for_scope(account_name=account_name, mailbox=mailbox)
        for email in emails:
            metadata = None
            uid = email.get("uid")
            if uid is not None:
                metadata = by_uid.get((str(email.get("uidvalidity", "") or ""), int(uid)))
            if metadata is None and email.get("message_id"):
                metadata = by_message_id.get(email["message_id"])
            if metadata is None:
                continue
            for field, value in metadata.items():
                if not email.get(field):
                    email[field] = value
            if self._engine:
                self._engine._normalize_email(email)

    def _delete_messages(self, emails: list[dict]) -> None:
        if not emails:
            return
        conn = _connect()
        try:
            for email in emails:
                conn.execute(
                    """
                    DELETE FROM email_messages
                    WHERE user_id = ? AND account_name = ? AND mailbox = ? AND uidvalidity = ? AND uid = ?
                    """,
                    (
                        self._session.user_id,
                        email.get("account", self._engine.account if self._engine else ""),
                        email.get("mailbox", TARGET_MAILBOX),
                        str(email.get("uidvalidity", "") or ""),
                        int(email.get("uid") or 0),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _save_cached_engine(self) -> None:
        if not self._engine or not self._enc_key:
            return
        now = time.time()
        payload = {
            "mail_engine": self._engine.to_dict(),
            "saved_at": now,
        }
        encrypted = encrypt_payload(payload, self._enc_key)
        blob = json.dumps(encrypted).encode()
        conn = _connect()
        conn.execute(
            """
            INSERT INTO email_cache (user_id, account_name, mailbox, encrypted_blob, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, account_name, mailbox)
            DO UPDATE SET encrypted_blob = excluded.encrypted_blob, updated_at = excluded.updated_at
            """,
            (self._session.user_id, self._cache_account_key(), "Inbox", blob, now),
        )
        conn.commit()
        conn.close()

    def _feedback_guidance(self) -> str:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT action, ai_recommendation, email_subject, feedback_text
                FROM email_actions
                WHERE user_id = ? AND action IN ('feedback:good', 'feedback:bad')
                ORDER BY created_at DESC
                LIMIT 12
                """,
                (self._session.user_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return ""

        lines = ["Recent user feedback on mail recommendations:"]
        for action, recommendation, subject, feedback_text in rows:
            verdict = "accepted" if action == "feedback:good" else "rejected"
            rec = recommendation or "none"
            subj = subject or "(no subject)"
            note = f" Note: {feedback_text.strip()}" if isinstance(feedback_text, str) and feedback_text.strip() else ""
            lines.append(f"- User {verdict} recommendation '{rec}' for: {subj}.{note}")
        return "\n".join(lines)

    def current_page(self, page: int | None = None) -> MailListResult:
        engine = self._require_engine()
        if page is not None:
            engine.page = max(page, 0)
        result = engine._mail_list_result()
        return MailListResult(
            emails=result["emails"],
            page=result["page"],
            total_pages=result["total_pages"],
            total_emails=result["total_emails"],
            content=result["content"],
        )

    def fetch(self, count: int = 0, unread_only: bool = False, account: str = "", analyze: bool = True, preferences: str = "", folder: str = "") -> MailListResult:
        from src.core.mail_engine import MailEngine
        from src.core.config import MAIL_SUMMARY_COUNT, IMAP_ACCOUNTS

        mailbox = folder or TARGET_MAILBOX

        if not self._engine:
            self._engine = MailEngine(model=self._model, imap_accounts=self._session.imap_accounts)
        else:
            self._engine.model = self._load_model()

        try:
            self._engine.fetch(count=count or MAIL_SUMMARY_COUNT, unread_only=unread_only, account=account, mailbox=mailbox, analyze=False)
        except ValueError as e:
            raise ImapConnectionError(str(e))

        self._merge_persisted_metadata(self._engine.inbox, account_name=self._engine.account, mailbox=mailbox)
        effective_preferences = preferences if preferences.strip() else self._load_preferences()
        combined_guidance = "\n\n".join(
            part for part in [effective_preferences, self._feedback_guidance()] if part.strip()
        )
        if analyze:
            pending = [
                email for email in self._engine.inbox
                if not email.get("recommendation")
                and not email.get("summary")
                and not email.get("recommended_todo")
            ]
            if pending:
                folder_list = self._get_folder_list(account)
                self._engine.recommend(pending, guidance=combined_guidance, folders=folder_list)
        self._engine._sort_inbox()

        self._save_messages(self._engine.inbox)
        self._save_cached_engine()
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

        moved_emails = [
            email
            for index in indices
            if (email := engine._email_for_index(index)) is not None
        ]
        action_name = "delete" if folder == "Trash" else f"move:{folder.lower()}"
        self._log_actions(moved_emails, action_name)
        action = Action(type=ActionType.mail_move, indices=indices, folder=folder)
        message = engine.execute(action)
        self._delete_messages(moved_emails)
        self._save_cached_engine()
        return message

    def _log_actions(self, emails: list[dict], action: str, feedback_text: str = "") -> None:
        import time
        now = time.time()
        conn = _connect()
        try:
            for email in emails:
                conn.execute(
                    """
                    INSERT INTO email_actions
                        (user_id, action, email_from, email_subject, email_date,
                         email_account, email_uid, ai_recommendation, ai_summary, feedback_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._session.user_id,
                        action,
                        email.get("from", ""),
                        email.get("subject", ""),
                        email.get("date", ""),
                        email.get("account", ""),
                        int(email.get("uid") or 0),
                        email.get("recommendation", ""),
                        email.get("summary", ""),
                        feedback_text.strip(),
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def analyze(self, indices: list[int] | None = None, preferences: str = "") -> MailListResult:
        engine = self._require_engine()
        effective_preferences = preferences if preferences.strip() else self._load_preferences()
        combined_guidance = "\n\n".join(
            part for part in [effective_preferences, self._feedback_guidance()] if part.strip()
        )
        if indices:
            target = [
                email
                for index in indices
                if (email := engine._email_for_index(index)) is not None
            ]
        else:
            target = engine.inbox

        if target:
            engine.model = self._load_model()
            folder_list = self._get_folder_list()
            engine.recommend(target, guidance=combined_guidance, folders=folder_list)
            self._save_messages(engine.inbox)
            self._save_cached_engine()

        result = engine._mail_list_result()
        return MailListResult(
            emails=result["emails"],
            page=result["page"],
            total_pages=result["total_pages"],
            total_emails=result["total_emails"],
            content=result["content"],
        )

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
            body_html=email.get("body_html", ""),
            account=email.get("account", ""),
            uid=email.get("uid"),
            recommendation=email.get("recommendation", ""),
            summary=email.get("summary", ""),
            recommended_todo=email.get("recommended_todo", ""),
            attachments=email.get("attachments", []),
        )

    def mark_read(self, index: int) -> None:
        engine = self._require_engine()
        email = engine._email_for_index(index)
        if email is None:
            raise EmailNotFoundError(f"No email at index {index}")

        uid = email.get("uid")
        if uid is None:
            return

        from src.core.actions.mail import mark_read_by_uids

        try:
            mark_read_by_uids(
                [int(uid)],
                mailbox=email.get("mailbox", TARGET_MAILBOX),
                account_name=email.get("account", self._engine.account if self._engine else ""),
                imap_accounts=self._session.imap_accounts,
            )
        except NotImplementedError:
            return

        email["read"] = True
        self._save_messages(engine.inbox)
        self._save_cached_engine()

    def record_feedback(self, index: int, verdict: str, text: str = "") -> None:
        engine = self._require_engine()
        email = engine._email_for_index(index)
        if email is None:
            raise EmailNotFoundError(f"No email at index {index}")
        action = "feedback:good" if verdict == "good" else "feedback:bad"
        self._log_actions([email], action, feedback_text=text)

    def handle(self, prompt: str, interactive: bool = False) -> list[dict]:
        engine = self._require_engine()
        return engine.handle(prompt, interactive=interactive)

    def to_dict(self) -> dict | None:
        return self._engine.to_dict() if self._engine else None
