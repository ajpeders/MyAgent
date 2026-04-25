"""Hybrid mail engine with deterministic state, display, and execution."""
import json
import re

from src.core.actions.action import Action, ActionType, Plan
from src.core.actions.mail import (
    read_emails as mail_read_emails,
    move_by_uids as mail_move_by_uids,
    refresh_mail as mail_refresh,
    email_matches as mail_email_matches,
)
from src.core.config import MAIL_SUMMARY_COUNT, TARGET_MAILBOX
from src.services.llm.adapters import default_adapter


class MailEngine:
    """Stateful mail engine that owns inbox cache and mail operations."""

    _RECOMMEND_SYSTEM = (
        "You are an email classifier. For each email, return a recommendation: "
        "delete, keep, or save. Return JSON matching the schema."
    )
    _RECOMMEND_SCHEMA = {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "action": {"type": "string", "enum": ["delete", "keep", "save"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["index", "action"],
                },
            }
        },
        "required": ["recommendations"],
    }
    _INTENT_SYSTEM = (
        "You parse user email commands into actions. The current inbox page is provided. "
        "Return a plan as JSON. Use indices (1-based, relative to the current page) "
        "to reference emails. For deletes, use mail_move with folder='Trash'. "
        "For saves, use mail_move with folder='Saved'. For reading, use answer with "
        "the email index. For fetching more, use mail_read. To end, use done. "
        "Do not generate display text."
    )

    def __init__(self, model: str, page_size: int = 20, imap_accounts: list[dict] | None = None):
        self.inbox: list[dict] = []
        self.account: str = ""
        self.model: str = model
        self.page: int = 0
        self.page_size: int = page_size
        self.imap_accounts: list[dict] | None = imap_accounts

    # -- Display -----------------------------------------------------------

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.inbox) + self.page_size - 1) // self.page_size)

    def current_page(self) -> list[dict]:
        """Return emails on the current page."""
        start = self.page * self.page_size
        end = start + self.page_size
        return self.inbox[start:end]

    def current_page_emails(self) -> list[dict]:
        """Compatibility alias for current_page()."""
        return self.current_page()

    def display(self) -> str:
        """Render the current page as a deterministic numbered list."""
        if not self.inbox:
            return "[mail] Inbox is empty."

        page_emails = self.current_page()
        lines: list[str] = []

        if self.total_pages > 1:
            start = self.page * self.page_size + 1
            end = min(start + self.page_size - 1, len(self.inbox))
            lines.append(
                f"[Page {self.page + 1}/{self.total_pages}] "
                f"Showing {start}-{end} of {len(self.inbox)}"
            )
            lines.append("")

        for i, email in enumerate(page_emails, start=1):
            sender = email.get("from", "unknown")
            subject = email.get("subject", "(no subject)")
            rec = email.get("recommendation", "")
            rec_tag = f"  [{rec}]" if rec else ""
            lines.append(f"{i:>3}. {sender} - {subject}{rec_tag}")

        return "\n".join(lines)

    def display_email(self, index: int) -> str:
        """Show full details for a single email by page-relative index."""
        email = self._email_for_index(index)
        if email is None:
            return f"[mail] Invalid index: {index}."

        lines = [
            f"FROM: {email.get('from', 'unknown')}",
            f"SUBJECT: {email.get('subject', '(no subject)')}",
            f"DATE: {email.get('date', '')}",
            f"ACCOUNT: {email.get('account', '')}",
            "",
            email.get("body", "(no body)"),
        ]
        return "\n".join(lines)

    # -- State -------------------------------------------------------------

    def _absolute_index(self, page_index: int) -> int | None:
        """Convert a 1-based page index to a 0-based inbox index."""
        if page_index < 1 or page_index > len(self.current_page()):
            return None
        return self.page * self.page_size + page_index - 1

    def _email_for_index(self, page_index: int) -> dict | None:
        absolute = self._absolute_index(page_index)
        if absolute is None:
            return None
        return self.inbox[absolute]

    def remove_by_indices(self, indices: list[int]) -> list[dict]:
        """Remove emails by 1-based page-relative indices."""
        absolute_indices = sorted(
            {
                absolute
                for index in indices
                if (absolute := self._absolute_index(index)) is not None
            },
            reverse=True,
        )
        removed = []
        for absolute in absolute_indices:
            removed.append(self.inbox.pop(absolute))

        if self.page >= self.total_pages:
            self.page = max(0, self.total_pages - 1)

        return list(reversed(removed))

    def get_uids_for_indices(self, indices: list[int]) -> list[int]:
        """Resolve 1-based page-relative indices to cached UIDs."""
        uids = []
        for index in indices:
            email = self._email_for_index(index)
            if email is not None and email.get("uid") is not None:
                uids.append(email["uid"])
        return uids

    def _indices_for_filter(self, action: Action) -> list[int]:
        """Backward-compatible filter matching, scoped to the current page."""
        indices = []
        for index, email in enumerate(self.current_page(), start=1):
            if mail_email_matches(email, action.filter_from, action.filter_subject):
                indices.append(index)
        return indices

    # -- Pagination --------------------------------------------------------

    def next_page(self) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1

    def prev_page(self) -> None:
        if self.page > 0:
            self.page -= 1

    def go_to_page(self, page_num: int) -> None:
        self.page = max(0, min(page_num - 1, self.total_pages - 1))

    # -- Serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize engine state for the session mail_engine field.

        imap_accounts are intentionally excluded — they live in session.imap_accounts
        and are injected by the executor when restoring the engine.
        """
        return {
            "inbox": self.inbox,
            "account": self.account,
            "model": self.model,
            "page": self.page,
            "page_size": self.page_size,
        }

    @classmethod
    def from_dict(cls, data: dict, imap_accounts: list[dict] | None = None) -> "MailEngine":
        """Restore engine state from the session. Pass imap_accounts from session.imap_accounts."""
        engine = cls(model=data.get("model", ""), page_size=data.get("page_size", 20), imap_accounts=imap_accounts)
        engine.inbox = data.get("inbox", [])
        engine.account = data.get("account", "")
        engine.page = data.get("page", 0)
        return engine

    # -- LLM calls ---------------------------------------------------------

    def _emails_for_llm(self, emails: list[dict] | None = None) -> str:
        target = emails if emails is not None else self.current_page()
        lines = []
        for i, email in enumerate(target, start=1):
            lines.append(
                f"{i}. FROM: {email.get('from', 'unknown')}\n"
                f"   SUBJECT: {email.get('subject', '(no subject)')}\n"
                f"   DATE: {email.get('date', '')}\n"
                f"   RECOMMENDATION: {email.get('recommendation', '')}\n"
                f"   BODY: {email.get('body', '')[:200]}"
            )
        return "\n---\n".join(lines)

    def recommend(self, emails: list[dict] | None = None) -> None:
        """Tag emails with recommendations, defaulting to keep on failure."""
        target = emails if emails is not None else self.inbox
        if not target:
            return

        try:
            messages = [
                {"role": "system", "content": self._RECOMMEND_SYSTEM},
                {"role": "user", "content": f"Emails:\n{self._emails_for_llm(target)}"},
            ]
            raw = default_adapter.complete_sync(messages, self._RECOMMEND_SCHEMA, self.model)
            data = json.loads(raw)
            recommendations = {
                rec["index"]: rec["action"]
                for rec in data.get("recommendations", [])
                if rec.get("action") in {"delete", "keep", "save"}
            }
            for i, email in enumerate(target, start=1):
                email["recommendation"] = recommendations.get(i, "keep")
        except Exception:
            for email in target:
                email["recommendation"] = "keep"

    def parse_intent(self, user_input: str) -> Plan:
        """Parse a user mail command into executable actions."""
        from src.core.tools import MAIL_TOOLS
        from src.core.tools.schema import build_plan_schema

        messages = [
            {"role": "system", "content": self._INTENT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"User says: {user_input!r}\n\n"
                    f"Current inbox page:\n{self.display()}"
                ),
            },
        ]
        try:
            raw = default_adapter.complete_sync(messages, build_plan_schema(MAIL_TOOLS), self.model)
            if not raw or not raw.strip():
                return Plan(actions=[Action(type=ActionType.done)])
            return Plan.model_validate_json(raw)
        except Exception:
            return Plan(actions=[Action(type=ActionType.done)])

    # -- IMAP operations ---------------------------------------------------

    def fetch(self, count: int = 0, unread_only: bool = False, account: str = "") -> None:
        """Fetch emails and populate the inbox cache."""
        self.account = account or self.account
        mail_refresh()
        self.inbox = mail_read_emails(
            count=count or MAIL_SUMMARY_COUNT,
            unread_only=unread_only,
            mailbox=TARGET_MAILBOX,
            account_name=self.account,
            imap_accounts=self.imap_accounts,
        )
        self.page = 0
        self.recommend()

    def execute(self, action: Action) -> str:
        """Execute one deterministic action and return a result message."""
        if action.type == ActionType.done:
            return "[done] Mail session ended."

        if action.type == ActionType.answer:
            if action.indices:
                return self.display_email(action.indices[0])
            return action.content

        if action.type == ActionType.mail_read:
            self.fetch(
                count=action.count,
                unread_only=action.unread_only,
                account=action.account,
            )
            label = "unread" if action.unread_only else "all"
            return f"[mail] Fetched {len(self.inbox)} {label} emails"

        if action.type == ActionType.mail_read_all:
            from src.core.actions.mail import read_all_emails
            self.inbox = read_all_emails(mailbox=action.mailbox, account_name=action.account, imap_accounts=self.imap_accounts)
            self.page = 0
            self.recommend()
            return f"[mail] Synced {len(self.inbox)} emails from {action.mailbox}"

        if action.type == ActionType.mail_create_folder:
            from src.core.actions.mail import create_folder
            success = create_folder(folder_name=action.folder_name, account_name=action.account, imap_accounts=self.imap_accounts)
            return f"[mail] Folder '{action.folder_name}' created." if success else f"[mail] Failed to create folder '{action.folder_name}'."

        if action.type == ActionType.mail_move:
            indices = action.indices or self._indices_for_filter(action)
            if not indices:
                return "[mail] No emails specified."

            selected = [
                (index, email)
                for index in indices
                if (email := self._email_for_index(index)) is not None
            ]
            if not selected:
                return "[mail] No matching emails found."

            moved = 0
            by_account: dict[str, list[int]] = {}
            for _index, email in selected:
                uid = email.get("uid")
                if uid is None:
                    continue
                account = action.account or email.get("account", "") or self.account
                by_account.setdefault(account, []).append(uid)

            if not by_account:
                return "[mail] No UIDs available for selected emails."

            try:
                for account, uids in by_account.items():
                    moved += mail_move_by_uids(
                        uids,
                        folder=action.folder,
                        mailbox=TARGET_MAILBOX,
                        account_name=account,
                        imap_accounts=self.imap_accounts,
                    )
            except NotImplementedError as exc:
                return f"[mail] {exc}"

            if moved:
                self.remove_by_indices(indices)
                dest = "Deleted" if action.folder == "Trash" else f"Moved to {action.folder}"
                return f"[mail] {dest} {moved} emails - {len(self.inbox)} remaining"

            return "[mail] No matching emails found. Refresh may be needed."

        if action.type == ActionType.summary:
            return self.display()

        return action.content or f"[mail] Unknown action: {action.type.value}"

    # -- Main entry point --------------------------------------------------

    def handle(self, user_input: str, *, interactive: bool = False) -> list[dict]:
        """Parse user input, execute safe actions, and return structured results."""
        nav_result = self._handle_navigation(user_input)
        if nav_result is not None:
            return [nav_result]

        plan = self.parse_intent(user_input)
        results: list[dict] = []
        needs_display = False

        for action in plan.actions:
            if action.type == ActionType.done:
                results.append({"type": "done", "content": "Mail session ended.", "agent": "mail"})
                break

            if action.type == ActionType.mail_move:
                indices = action.indices or self._indices_for_filter(action)
                indices_str = ", ".join(str(index) for index in indices) or "none"
                dest = "Delete" if action.folder == "Trash" else f"Move to {action.folder}"
                pending = action.model_dump()
                pending["indices"] = indices
                results.append({
                    "type": "confirm",
                    "content": f"{dest} email(s) {indices_str}?",
                    "agent": "mail",
                    "pending": pending,
                    "pending_confirm": "mail_move",
                })
                break

            if action.type == ActionType.answer:
                results.append({
                    "type": "answer",
                    "content": self.execute(action),
                    "agent": "mail",
                })
                needs_display = True
                continue

            if action.type == ActionType.mail_read:
                message = self.execute(action)
                results.append(self._mail_list_result(message))
                continue

            if action.type == ActionType.mail_read_all:
                message = self.execute(action)
                results.append(self._mail_list_result(message))
                continue

            if action.type == ActionType.mail_create_folder:
                message = self.execute(action)
                results.append({
                    "type": "mail_create_folder",
                    "content": message,
                    "agent": "mail",
                })
                continue

            if action.type == ActionType.summary:
                results.append(self._mail_list_result())
                continue

            if action.type in (ActionType.warning, ActionType.note, ActionType.remember):
                results.append({
                    "type": action.type.value,
                    "content": action.content,
                    "agent": "mail",
                })
                continue

            if action.type == ActionType.ask_user:
                results.append({"type": "ask_user", "content": action.content, "agent": "mail"})
                break

        if needs_display and not any(result["type"] in {"done", "confirm", "mail_list"} for result in results):
            results.append(self._mail_list_result())

        return results

    def _handle_navigation(self, user_input: str) -> dict | None:
        normalized = user_input.strip().lower()
        if normalized in {"next", "next page", "more"}:
            self.next_page()
            return self._mail_list_result()
        if normalized in {"prev", "previous", "previous page", "back"}:
            self.prev_page()
            return self._mail_list_result()

        match = re.fullmatch(r"page\s+(\d+)", normalized)
        if match:
            self.go_to_page(int(match.group(1)))
            return self._mail_list_result()

        return None

    def _mail_list_result(self, message: str = "") -> dict:
        """Build a structured mail list result for CLI and API clients."""
        display = self.display()
        content = f"{message}\n\n{display}" if message else display
        return {
            "type": "mail_list",
            "content": content,
            "agent": "mail",
            "emails": [
                {
                    "index": index,
                    "from": email.get("from", ""),
                    "subject": email.get("subject", ""),
                    "date": email.get("date", ""),
                    "recommendation": email.get("recommendation", ""),
                    "account": email.get("account", ""),
                }
                for index, email in enumerate(self.current_page(), start=1)
            ],
            "page": self.page + 1,
            "total_pages": self.total_pages,
            "total_emails": len(self.inbox),
        }
