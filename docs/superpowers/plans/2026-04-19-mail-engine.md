# Mail Engine Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the buggy LLM-driven `mail_loop()` with a hybrid `MailEngine` where code handles state/display/execution deterministically and the LLM is a stateless intent parser + recommendation tagger.

**Architecture:** New `mail_engine.py` owns inbox cache, pagination, display formatting, and execution. LLM is called twice per interaction cycle: once for recommendations (after fetch) and once for intent parsing (per user input). Each LLM call gets fresh context — no conversation history accumulates.

**Tech Stack:** Python 3.12, Pydantic, IMAPClient, Ollama (qwen3:8b), SQLite (session persistence), FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-04-19-mail-engine-redesign.md`

---

## Implementation Tracker

Status here tracks implementation in this working tree. Per-task commit substeps below are intentionally left unchecked because no commit was requested.

- [x] Task 1: Action model — add `indices` field, remove `mail_save`
- [x] Task 2: MailEngine — display and state management
- [x] Task 3: MailEngine — pagination
- [x] Task 4: MailEngine — serialization
- [x] Task 5: MailEngine — recommendation LLM call
- [x] Task 6: MailEngine — intent parsing LLM call
- [x] Task 7: MailEngine — fetch and execute
- [x] Task 8: MailEngine — `handle()` entry point
- [x] Task 9: Update SessionState for MailEngine
- [x] Task 10: Wire MailEngine into `executor.py`
- [x] Task 11: Wire MailEngine into CLI
- [x] Task 12: Update `server.py` for structured mail responses
- [x] Task 13: Update mail agent system prompt
- [x] Task 14: Update `tools/schema.py` for `indices` field
- [x] Task 15: Final integration test
- [x] Task 16: Clean up and update docs

---

## Chunk 1: Core MailEngine (state, display, execute)

### Task 1: Action model — add `indices` field, remove `mail_save`

**Files:**
- Modify: `actions/action.py`
- Modify: `tools/registry.py` (remove `MAIL_SAVE`)
- Modify: `tools/__init__.py` (remove `MAIL_SAVE` import)
- Test: `tests/test_action.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_action.py
import json
from actions.action import Action, ActionType, Plan

class TestActionIndex:
    def test_action_has_indices_field(self):
        a = Action(type=ActionType.mail_move, indices=[1, 3], folder="Trash")
        assert a.indices == [1, 3]

    def test_action_indices_default_empty(self):
        a = Action(type=ActionType.mail_move, folder="Trash")
        assert a.indices == []

    def test_action_serializes_indices(self):
        a = Action(type=ActionType.mail_move, indices=[2], folder="Trash")
        data = json.loads(a.model_dump_json())
        assert data["indices"] == [2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_action.py -v`
Expected: FAIL — `indices` field does not exist on Action

- [ ] **Step 3: Add `indices` field to Action model and remove `mail_save`**

In `actions/action.py`:
- Add `indices: list[int] = []` to the `Action` class
- Remove `mail_save = "mail_save"` from `ActionType` enum

```python
class ActionType(str, Enum):
    misc        = "misc"
    answer      = "answer"
    summary     = "summary"
    warning     = "warning"
    command     = "command"
    mail_read   = "mail_read"
    mail_move   = "mail_move"
    # mail_save removed — use mail_move with folder="Saved"
    ask_user    = "ask_user"
    note        = "note"
    remember    = "remember"
    web_search  = "web_search"
    personal_data = "personal_data"
    done        = "done"


class Action(BaseModel):
    type: ActionType
    content: str = ""
    count: int = 10
    unread_only: bool = False
    folder: str = "Trash"
    filter_from: str = ""
    filter_subject: str = ""
    account: str = ""
    indices: list[int] = []           # page-relative email indices
    continue_conversation: bool = False
```

In `tools/registry.py`:
- Remove the `MAIL_SAVE` ToolDef
- Remove `MAIL_SAVE` from `MAIL_TOOLS` list

In `tools/__init__.py`:
- Remove `MAIL_SAVE` from imports

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_action.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add actions/action.py tools/registry.py tools/__init__.py tests/test_action.py
git commit -m "feat: add indices field to Action, remove mail_save (now mail_move with folder)"
```

---

### Task 2: MailEngine — display and state management

**Files:**
- Create: `mail_engine.py`
- Test: `tests/test_mail_engine.py` (create)

- [ ] **Step 1: Write the failing tests for display and state**

```python
# tests/test_mail_engine.py
import pytest
from mail_engine import MailEngine

FAKE_EMAILS = [
    {"uid": 101, "from": "alice@test.com", "subject": "Hello", "date": "2026-04-19", "body": "Hi there", "account": "Gmail"},
    {"uid": 102, "from": "bob@test.com", "subject": "Meeting", "date": "2026-04-19", "body": "At 3pm", "account": "Gmail"},
    {"uid": 103, "from": "carol@test.com", "subject": "Promo", "date": "2026-04-19", "body": "Buy now", "account": "Yahoo"},
]


class TestDisplay:
    def test_display_empty_inbox(self):
        engine = MailEngine(model="test")
        assert engine.display() == "[mail] Inbox is empty."

    def test_display_shows_numbered_list(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]
        output = engine.display()
        assert "1." in output
        assert "alice@test.com" in output or "Hello" in output
        assert "2." in output
        assert "3." in output

    def test_display_shows_recommendations(self):
        engine = MailEngine(model="test")
        emails = [e.copy() for e in FAKE_EMAILS]
        emails[0]["recommendation"] = "delete"
        emails[1]["recommendation"] = "keep"
        engine.inbox = emails
        output = engine.display()
        assert "[delete]" in output
        assert "[keep]" in output

    def test_display_email_by_index(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]
        output = engine.display_email(1)
        assert "alice@test.com" in output
        assert "Hello" in output
        assert "Hi there" in output

    def test_display_email_invalid_index(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]
        output = engine.display_email(99)
        assert "invalid" in output.lower()


class TestState:
    def test_remove_by_indices(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]
        engine.remove_by_indices([1, 3])  # remove alice and carol
        assert len(engine.inbox) == 1
        assert engine.inbox[0]["subject"] == "Meeting"

    def test_remove_by_indices_out_of_range_skipped(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]
        engine.remove_by_indices([1, 99])  # 99 is out of range
        assert len(engine.inbox) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: FAIL — `mail_engine` module does not exist

- [ ] **Step 3: Implement MailEngine with display and state methods**

```python
# mail_engine.py
"""Hybrid mail engine — deterministic state/display, LLM for intent parsing.

This module owns the inbox cache, display formatting, pagination, and
execution of mail actions. The LLM is called only for recommendations
(after fetch) and intent parsing (per user input). Each LLM call gets
fresh context with no conversation history.
"""
from actions.action import Action, ActionType, Plan


class MailEngine:
    """Stateful mail engine — owns inbox, display, and execution."""

    def __init__(self, model: str, page_size: int = 20):
        self.inbox: list[dict] = []
        self.account: str = ""
        self.model: str = model
        self.page: int = 0
        self.page_size: int = page_size

    # ── Display (deterministic) ─────────────────────────────────────────────

    def current_page_emails(self) -> list[dict]:
        """Return the emails on the current page."""
        start = self.page * self.page_size
        end = start + self.page_size
        return self.inbox[start:end]

    def display(self) -> str:
        """Render the current page as a formatted, numbered list."""
        if not self.inbox:
            return "[mail] Inbox is empty."

        page_emails = self.current_page_emails()
        total_pages = max(1, (len(self.inbox) + self.page_size - 1) // self.page_size)
        lines = []

        if total_pages > 1:
            start = self.page * self.page_size + 1
            end = min(start + self.page_size - 1, len(self.inbox))
            lines.append(f"[Page {self.page + 1}/{total_pages}] Showing {start}-{end} of {len(self.inbox)}")
            lines.append("")

        for i, email in enumerate(page_emails, start=self.page * self.page_size + 1):
            sender = email.get("from", "unknown")
            subject = email.get("subject", "(no subject)")
            rec = email.get("recommendation", "")
            rec_tag = f"  [{rec}]" if rec else ""
            lines.append(f"{i:>3}. {sender} — {subject}{rec_tag}")

        return "\n".join(lines)

    def display_email(self, index: int) -> str:
        """Show full details of a single email by 1-based index."""
        if index < 1 or index > len(self.inbox):
            return f"[mail] Invalid index: {index}. Inbox has {len(self.inbox)} emails."

        email = self.inbox[index - 1]
        lines = [
            f"FROM: {email.get('from', 'unknown')}",
            f"SUBJECT: {email.get('subject', '(no subject)')}",
            f"DATE: {email.get('date', '')}",
            f"ACCOUNT: {email.get('account', '')}",
            "",
            email.get("body", "(no body)"),
        ]
        return "\n".join(lines)

    # ── State management ────────────────────────────────────────────────────

    def remove_by_indices(self, indices: list[int]) -> list[dict]:
        """Remove emails by 1-based indices. Returns removed emails."""
        valid = sorted(set(i for i in indices if 1 <= i <= len(self.inbox)), reverse=True)
        removed = []
        for i in valid:
            removed.append(self.inbox.pop(i - 1))
        # Fix page if it's now out of range
        total_pages = max(1, (len(self.inbox) + self.page_size - 1) // self.page_size)
        if self.page >= total_pages:
            self.page = max(0, total_pages - 1)
        return removed

    def get_uids_for_indices(self, indices: list[int]) -> list[int]:
        """Resolve 1-based indices to UIDs from the inbox cache."""
        uids = []
        for i in indices:
            if 1 <= i <= len(self.inbox):
                uid = self.inbox[i - 1].get("uid")
                if uid is not None:
                    uids.append(uid)
        return uids
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mail_engine.py tests/test_mail_engine.py
git commit -m "feat: add MailEngine with deterministic display and state management"
```

---

### Task 3: MailEngine — pagination

**Files:**
- Modify: `mail_engine.py`
- Test: `tests/test_mail_engine.py`

- [ ] **Step 1: Write the failing pagination tests**

Append to `tests/test_mail_engine.py`:

```python
class TestPagination:
    def _engine_with_emails(self, count: int, page_size: int = 3) -> MailEngine:
        engine = MailEngine(model="test", page_size=page_size)
        engine.inbox = [
            {"uid": i, "from": f"user{i}@test.com", "subject": f"Email {i}",
             "date": "2026-04-19", "body": f"Body {i}", "account": "Gmail"}
            for i in range(1, count + 1)
        ]
        return engine

    def test_first_page_shows_page_size_emails(self):
        engine = self._engine_with_emails(10, page_size=3)
        page = engine.current_page_emails()
        assert len(page) == 3
        assert page[0]["subject"] == "Email 1"

    def test_next_page(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.next_page()
        assert engine.page == 1
        page = engine.current_page_emails()
        assert page[0]["subject"] == "Email 4"

    def test_prev_page_at_start_stays(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.prev_page()
        assert engine.page == 0

    def test_next_page_at_end_stays(self):
        engine = self._engine_with_emails(10, page_size=3)
        for _ in range(20):
            engine.next_page()
        total_pages = (10 + 2) // 3  # ceil(10/3) = 4
        assert engine.page == total_pages - 1

    def test_go_to_page(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.go_to_page(3)  # 1-based
        assert engine.page == 2  # 0-based internal

    def test_display_shows_page_header_when_multiple_pages(self):
        engine = self._engine_with_emails(10, page_size=3)
        output = engine.display()
        assert "Page 1/" in output
        assert "Showing 1-3 of 10" in output

    def test_display_no_page_header_single_page(self):
        engine = self._engine_with_emails(3, page_size=20)
        output = engine.display()
        assert "Page" not in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestPagination -v`
Expected: FAIL — `next_page`, `prev_page`, `go_to_page` do not exist

- [ ] **Step 3: Add pagination methods to MailEngine**

Add to `mail_engine.py` in the MailEngine class, after `get_uids_for_indices`:

```python
    # ── Pagination ──────────────────────────────────────────────────────────

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.inbox) + self.page_size - 1) // self.page_size)

    def next_page(self) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1

    def prev_page(self) -> None:
        if self.page > 0:
            self.page -= 1

    def go_to_page(self, page_num: int) -> None:
        """Go to a page by 1-based page number."""
        target = max(0, min(page_num - 1, self.total_pages - 1))
        self.page = target
```

Also update `display()` to use `self.total_pages`:

```python
    def display(self) -> str:
        if not self.inbox:
            return "[mail] Inbox is empty."

        page_emails = self.current_page_emails()
        lines = []

        if self.total_pages > 1:
            start = self.page * self.page_size + 1
            end = min(start + self.page_size - 1, len(self.inbox))
            lines.append(f"[Page {self.page + 1}/{self.total_pages}] Showing {start}-{end} of {len(self.inbox)}")
            lines.append("")

        for i, email in enumerate(page_emails, start=self.page * self.page_size + 1):
            sender = email.get("from", "unknown")
            subject = email.get("subject", "(no subject)")
            rec = email.get("recommendation", "")
            rec_tag = f"  [{rec}]" if rec else ""
            lines.append(f"{i:>3}. {sender} — {subject}{rec_tag}")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mail_engine.py tests/test_mail_engine.py
git commit -m "feat: add pagination to MailEngine"
```

---

### Task 4: MailEngine — serialization

**Files:**
- Modify: `mail_engine.py`
- Test: `tests/test_mail_engine.py`

- [ ] **Step 1: Write failing serialization tests**

Append to `tests/test_mail_engine.py`:

```python
class TestSerialization:
    def test_to_dict_and_back(self):
        engine = MailEngine(model="qwen3:8b", page_size=5)
        engine.inbox = [FAKE_EMAILS[0].copy()]
        engine.inbox[0]["recommendation"] = "keep"
        engine.account = "Gmail"
        engine.page = 2

        data = engine.to_dict()
        restored = MailEngine.from_dict(data)

        assert restored.model == "qwen3:8b"
        assert restored.page_size == 5
        assert restored.page == 2
        assert restored.account == "Gmail"
        assert len(restored.inbox) == 1
        assert restored.inbox[0]["recommendation"] == "keep"

    def test_to_dict_is_json_serializable(self):
        import json
        engine = MailEngine(model="test")
        engine.inbox = [FAKE_EMAILS[0].copy()]
        data = engine.to_dict()
        serialized = json.dumps(data)
        assert isinstance(serialized, str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestSerialization -v`
Expected: FAIL — `to_dict` / `from_dict` do not exist

- [ ] **Step 3: Add serialization methods**

Add to `mail_engine.py` in the MailEngine class:

```python
    # ── Serialization ───────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize engine state for session storage."""
        return {
            "inbox": self.inbox,
            "account": self.account,
            "model": self.model,
            "page": self.page,
            "page_size": self.page_size,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MailEngine":
        """Restore engine from serialized state."""
        engine = cls(model=data["model"], page_size=data.get("page_size", 20))
        engine.inbox = data.get("inbox", [])
        engine.account = data.get("account", "")
        engine.page = data.get("page", 0)
        return engine
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mail_engine.py tests/test_mail_engine.py
git commit -m "feat: add MailEngine serialization for session persistence"
```

---

## Chunk 2: LLM integration + IMAP execution

### Task 5: MailEngine — recommendation LLM call

**Files:**
- Modify: `mail_engine.py`
- Test: `tests/test_mail_engine.py`

The `recommend()` method calls the LLM once with a list of emails and gets back a recommendation per email. If the LLM fails, all emails default to `[keep]`.

- [ ] **Step 1: Write failing recommendation tests**

Append to `tests/test_mail_engine.py`:

```python
import json
from unittest.mock import patch

class TestRecommend:
    def test_recommend_tags_emails(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        llm_response = json.dumps({
            "recommendations": [
                {"index": 1, "action": "keep"},
                {"index": 2, "action": "keep"},
                {"index": 3, "action": "delete"},
            ]
        })

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = llm_response
            engine.recommend()

        assert engine.inbox[0]["recommendation"] == "keep"
        assert engine.inbox[1]["recommendation"] == "keep"
        assert engine.inbox[2]["recommendation"] == "delete"

    def test_recommend_defaults_to_keep_on_failure(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.side_effect = Exception("LLM down")
            engine.recommend()

        for email in engine.inbox:
            assert email.get("recommendation") == "keep"

    def test_recommend_defaults_to_keep_on_bad_json(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = "not json"
            engine.recommend()

        for email in engine.inbox:
            assert email.get("recommendation") == "keep"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestRecommend -v`
Expected: FAIL — `recommend` does not exist or missing import

- [ ] **Step 3: Implement recommend()**

Add to the top of `mail_engine.py`:

```python
import json

from llm import default_adapter
```

Add to the MailEngine class:

```python
    # ── LLM calls ──────────────────────────────────────────────────────────

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
                    },
                    "required": ["index", "action"],
                },
            }
        },
        "required": ["recommendations"],
    }

    def _emails_for_llm(self, emails: list[dict] | None = None) -> str:
        """Format emails for LLM context. Uses current page if no list given."""
        target = emails if emails is not None else self.current_page_emails()
        lines = []
        for i, e in enumerate(target, start=1):
            lines.append(
                f"{i}. FROM: {e.get('from', 'unknown')}\n"
                f"   SUBJECT: {e.get('subject', '(no subject)')}\n"
                f"   DATE: {e.get('date', '')}\n"
                f"   BODY: {e.get('body', '')[:200]}"
            )
        return "\n---\n".join(lines)

    def recommend(self, emails: list[dict] | None = None) -> None:
        """Call LLM to tag emails with recommendations. Defaults all to 'keep' on failure."""
        target = emails if emails is not None else self.inbox
        if not target:
            return
        try:
            messages = [
                {"role": "system", "content": self._RECOMMEND_SYSTEM},
                {"role": "user", "content": f"Emails:\n{self._emails_for_llm(target)}"},
            ]
            raw = default_adapter.complete(messages, self._RECOMMEND_SCHEMA, self.model)
            data = json.loads(raw)
            recs = {r["index"]: r["action"] for r in data.get("recommendations", [])}
            for i, email in enumerate(target, start=1):
                email["recommendation"] = recs.get(i, "keep")
        except Exception:
            for email in target:
                email.setdefault("recommendation", "keep")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestRecommend -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mail_engine.py tests/test_mail_engine.py
git commit -m "feat: add LLM-powered email recommendations to MailEngine"
```

---

### Task 6: MailEngine — intent parsing LLM call

**Files:**
- Modify: `mail_engine.py`
- Modify: `tools/registry.py` (update MAIL_MOVE tool to use indices)
- Test: `tests/test_mail_engine.py`

The `parse_intent()` method sends the user's input + current page to the LLM and gets back a Plan.

- [ ] **Step 1: Write failing intent parsing tests**

Append to `tests/test_mail_engine.py`:

```python
from actions.action import Action, ActionType, Plan

class TestParseIntent:
    def test_parse_delete_returns_mail_move(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1, 3], folder="Trash")
        ]).model_dump_json()

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            plan = engine.parse_intent("delete 1 and 3")

        assert len(plan.actions) == 1
        assert plan.actions[0].type == ActionType.mail_move
        assert plan.actions[0].indices == [1, 3]

    def test_parse_intent_on_bad_response_returns_done(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = "garbage"
            plan = engine.parse_intent("delete 1")

        assert len(plan.actions) == 1
        assert plan.actions[0].type == ActionType.done
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestParseIntent -v`
Expected: FAIL — `parse_intent` does not exist

- [ ] **Step 3: Update MAIL_MOVE tool definition to use indices**

In `tools/registry.py`, update `MAIL_MOVE`. Note: `ParamType` only supports `"string"`, `"integer"`, `"boolean"` — so `indices` uses the existing Action model field (list[int]) which is already in the schema via `build_plan_schema()`. The tool description just tells the LLM how to use it:

```python
MAIL_MOVE = ToolDef(
    name="mail_move",
    description="Move or delete emails by index number. Set indices to the 1-based email numbers. Use folder='Trash' to delete.",
    params=[
        ParamDef("folder", "string", "Destination mailbox folder name.", required=True),
    ],
)
```

The `indices` field is already on the Action model and will appear in the plan schema automatically via `build_plan_schema()` (Task 14 adds it to the restricted model).

- [ ] **Step 4: Implement parse_intent()**

Add to `mail_engine.py` MailEngine class:

```python
    _INTENT_SYSTEM = (
        "You parse user email commands into actions. The current inbox page is provided. "
        "Return a plan as JSON. Use indices (1-based) to reference emails. "
        "For deletes, use mail_move with folder='Trash'. "
        "For reading, use answer with the email index. "
        "For fetching more, use mail_read. "
        "To end, use done."
    )

    def parse_intent(self, user_input: str) -> Plan:
        """Call LLM to classify user input into a Plan of actions."""
        from tools import MAIL_TOOLS
        from tools.schema import build_plan_schema

        page_text = self.display()
        messages = [
            {"role": "system", "content": self._INTENT_SYSTEM},
            {"role": "user", "content": f"User says: \"{user_input}\"\n\n{page_text}"},
        ]
        try:
            schema = build_plan_schema(MAIL_TOOLS)
            raw = default_adapter.complete(messages, schema, self.model)
            return Plan.model_validate_json(raw)
        except Exception:
            return Plan(actions=[Action(type=ActionType.done)])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add mail_engine.py tools/registry.py tests/test_mail_engine.py
git commit -m "feat: add intent parsing and update mail tools to index-based"
```

---

### Task 7: MailEngine — fetch and execute

**Files:**
- Modify: `mail_engine.py`
- Test: `tests/test_mail_engine.py`

Wire up IMAP operations through the mail dispatcher.

- [ ] **Step 1: Write failing execution tests**

Append to `tests/test_mail_engine.py`:

```python
class TestExecute:
    def test_fetch_populates_inbox(self):
        fake = [FAKE_EMAILS[0].copy()]
        engine = MailEngine(model="test")

        with patch("mail_engine.mail_read_emails", return_value=fake), \
             patch("mail_engine.mail_refresh"), \
             patch("mail_engine.default_adapter") as mock_llm:
            # Recommendation call
            mock_llm.complete.return_value = json.dumps({
                "recommendations": [{"index": 1, "action": "keep"}]
            })
            engine.fetch()

        assert len(engine.inbox) == 1
        assert engine.inbox[0]["subject"] == "Hello"
        assert engine.inbox[0]["recommendation"] == "keep"

    def test_execute_mail_move_removes_from_cache(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        action = Action(type=ActionType.mail_move, indices=[1], folder="Trash")

        with patch("mail_engine.mail_move_by_uids", return_value=1):
            result = engine.execute(action)

        assert len(engine.inbox) == 2
        assert "1" in result  # moved count
        assert engine.inbox[0]["subject"] == "Meeting"

    def test_execute_answer_returns_email_body(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        action = Action(type=ActionType.answer, indices=[2])
        result = engine.execute(action)

        assert "Meeting" in result
        assert "At 3pm" in result

    def test_execute_done_returns_done_message(self):
        engine = MailEngine(model="test")
        action = Action(type=ActionType.done)
        result = engine.execute(action)
        assert "ended" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestExecute -v`
Expected: FAIL — `fetch`, `execute` not implemented, missing imports

- [ ] **Step 3: Add fetch and execute to MailEngine**

First, add `move_by_uids` to the mail dispatcher. In `actions/mail.py`, add `move_by_uids` to both import branches:

```python
if IMAP_ACCOUNTS:
    from actions.mail_imap import (
        fetch_mailboxes, read_emails, move_emails,
        move_by_uids, refresh_mail, email_matches, emails_to_text,
    )
else:
    from actions.mail_applescript import (
        fetch_mailboxes, read_emails, move_emails,
        move_by_uids, refresh_mail, email_matches, emails_to_text,
    )
```

Note: the AppleScript backend will need a stub `move_by_uids` that raises `NotImplementedError` or routes through `move_emails`.

Then add imports at top of `mail_engine.py`:

```python
from actions.mail import (
    read_emails as mail_read_emails,
    move_by_uids as mail_move_by_uids,
    refresh_mail as mail_refresh,
    email_matches as mail_email_matches,
)
```

Add methods to MailEngine:

```python
    # ── IMAP operations ─────────────────────────────────────────────────────

    def fetch(self, count: int = 0, unread_only: bool = False, account: str = "") -> None:
        """Fetch emails from IMAP and populate inbox with recommendations."""
        from config import MAIL_SUMMARY_COUNT
        mail_refresh()
        acct = account or self.account
        emails = mail_read_emails(
            count=count or MAIL_SUMMARY_COUNT,
            unread_only=unread_only,
            mailbox="INBOX",
            account_name=acct,
        )
        self.inbox = emails
        self.page = 0
        self.recommend()

    def execute(self, action: Action) -> str:
        """Execute a single action. Returns a result message string."""
        if action.type == ActionType.done:
            return "[done] Mail session ended."

        elif action.type == ActionType.answer:
            idx = action.indices[0] if action.indices else 0
            return self.display_email(idx)

        elif action.type == ActionType.mail_move:
            if not action.indices:
                return "[mail] No emails specified."
            uids = self.get_uids_for_indices(action.indices)
            if not uids:
                return "[mail] No matching emails found."
            # Determine account from the first matched email
            first_email = self.inbox[action.indices[0] - 1]
            acct = action.account or first_email.get("account", "") or self.account
            moved = mail_move_by_uids(uids, folder=action.folder, account_name=acct)
            self.remove_by_indices(action.indices)
            dest = "Deleted" if action.folder == "Trash" else f"Moved to {action.folder}"
            return f"[mail] {dest} {moved} emails — {len(self.inbox)} remaining"

        elif action.type == ActionType.mail_read:
            self.fetch(count=action.count, unread_only=action.unread_only, account=action.account)
            label = "unread" if action.unread_only else "all"
            return f"[mail] Fetched {len(self.inbox)} {label} emails"

        elif action.type == ActionType.summary:
            return self.display()

        return f"[mail] Unknown action: {action.type}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mail_engine.py tests/test_mail_engine.py
git commit -m "feat: add fetch and execute methods to MailEngine"
```

---

### Task 8: MailEngine — handle() entry point

**Files:**
- Modify: `mail_engine.py`
- Test: `tests/test_mail_engine.py`

The `handle()` method is the main entry point. It takes user input, calls `parse_intent()`, executes each action, and returns structured results.

- [ ] **Step 1: Write failing handle tests**

Append to `tests/test_mail_engine.py`:

```python
class TestHandle:
    def test_handle_returns_results_list(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.answer, indices=[1])
        ]).model_dump_json()

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("read 1")

        assert len(results) >= 1
        assert results[0]["type"] == "answer"
        assert "Hello" in results[0]["content"]

    def test_handle_done_returns_done_result(self):
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.done)
        ]).model_dump_json()

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("done")

        assert any(r["type"] == "done" for r in results)

    def test_handle_mail_move_returns_confirm(self):
        """Non-interactive mode returns confirm instead of executing."""
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1], folder="Trash")
        ]).model_dump_json()

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("delete 1")

        assert results[0]["type"] == "confirm"
        assert results[0]["pending"] is not None

    def test_handle_redisplays_after_execute(self):
        """After a non-done action, the current page is included in results."""
        engine = MailEngine(model="test")
        engine.inbox = [e.copy() for e in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.answer, indices=[1])
        ]).model_dump_json()

        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("read 1")

        # Should have the answer + mail_list for redisplay
        types = [r["type"] for r in results]
        assert "answer" in types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py::TestHandle -v`
Expected: FAIL — `handle` not implemented

- [ ] **Step 3: Implement handle()**

Add to MailEngine class:

```python
    # ── Main entry point ────────────────────────────────────────────────────

    def handle(self, user_input: str, *, interactive: bool = False) -> list[dict]:
        """Parse user input via LLM, execute actions, return structured results.

        Returns list of result dicts with keys: type, content, agent,
        and optionally: emails, page, total_pages, total_emails, pending.
        """
        plan = self.parse_intent(user_input)
        results: list[dict] = []

        for action in plan.actions:
            if action.type == ActionType.done:
                results.append({"type": "done", "content": "Mail session ended.", "agent": "mail"})
                break

            elif action.type == ActionType.mail_move:
                if interactive:
                    # Interactive mode: caller handles confirmation via typer
                    result_msg = self.execute(action)
                    results.append({"type": "mail_move", "content": result_msg, "agent": "mail"})
                else:
                    # Non-interactive: return confirmation request
                    indices_str = ", ".join(str(i) for i in action.indices)
                    dest = "Delete" if action.folder == "Trash" else f"Move to {action.folder}"
                    results.append({
                        "type": "confirm",
                        "content": f"{dest} email(s) {indices_str}?",
                        "agent": "mail",
                        "pending": action.model_dump(),
                    })
                    break  # wait for confirmation

            elif action.type == ActionType.answer:
                content = self.execute(action)
                results.append({"type": "answer", "content": content, "agent": "mail"})

            elif action.type == ActionType.mail_read:
                content = self.execute(action)
                results.append(self._mail_list_result(content))

            elif action.type == ActionType.summary:
                results.append(self._mail_list_result())

            elif action.type == ActionType.ask_user:
                results.append({"type": "ask_user", "content": action.content, "agent": "mail"})
                break

        return results

    def _mail_list_result(self, message: str = "") -> dict:
        """Build a structured mail_list result with email data for the frontend."""
        page_emails = self.current_page_emails()
        return {
            "type": "mail_list",
            "content": f"{message}\n\n{self.display()}" if message else self.display(),
            "agent": "mail",
            "emails": [
                {
                    "index": self.page * self.page_size + i + 1,
                    "from": e.get("from", ""),
                    "subject": e.get("subject", ""),
                    "date": e.get("date", ""),
                    "recommendation": e.get("recommendation", ""),
                    "account": e.get("account", ""),
                }
                for i, e in enumerate(page_emails)
            ],
            "page": self.page + 1,
            "total_pages": self.total_pages,
            "total_emails": len(self.inbox),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mail_engine.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mail_engine.py tests/test_mail_engine.py
git commit -m "feat: add handle() entry point to MailEngine"
```

---

## Chunk 3: Integration — wire into executor, CLI, server

### Task 9: Update SessionState for MailEngine

**Files:**
- Modify: `session_store.py`
- Test: `tests/test_session_store.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_session_store.py
from session_store import SessionState

def test_session_state_has_mail_engine_field():
    state = SessionState(session_id="test", model="test")
    assert state.mail_engine is None

def test_session_state_serializes_mail_engine():
    state = SessionState(session_id="test", model="test")
    state.mail_engine = {"inbox": [], "page": 0, "model": "test", "page_size": 20, "account": ""}
    # Verify it doesn't crash and the field is accessible
    assert state.mail_engine["page"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_store.py -v`
Expected: FAIL — `mail_engine` field doesn't exist

- [ ] **Step 3: Add mail_engine field to SessionState**

In `session_store.py`, update the `SessionState` dataclass:

```python
@dataclass
class SessionState:
    session_id: str
    model: str
    active_agent: str | None = None
    contexts: dict[str, list[dict]] = field(default_factory=dict)
    inbox: list[dict] = field(default_factory=list)       # legacy, kept for compat
    mail_engine: dict | None = None                       # serialized MailEngine state
    pending: dict | None = None
```

Update `save_session` to include `mail_engine`:

```python
def save_session(state: SessionState) -> None:
    data = json.dumps({
        "session_id": state.session_id,
        "model": state.model,
        "active_agent": state.active_agent,
        "contexts": state.contexts,
        "inbox": state.inbox,
        "mail_engine": state.mail_engine,
        "pending": state.pending,
    })
    # ... rest unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add session_store.py tests/test_session_store.py
git commit -m "feat: add mail_engine field to SessionState"
```

---

### Task 10: Wire MailEngine into executor.py

**Files:**
- Modify: `executor.py`
- Test: `tests/test_e2e.py` (update existing tests)

Replace `mail_loop` and inline mail handling in `dispatch_actions` with `MailEngine`. Key design decision: when `active_agent == "mail"` and the engine exists, `dispatch_session` delegates directly to `engine.handle()` instead of going through the normal agent pipeline. This is the core architectural change — the mail agent's `plan()` is only used for the initial `mail_read` action; after that, the engine's own `parse_intent()` handles user input with fresh, stateless context.

- [ ] **Step 1: Remove old mail functions and update imports in executor.py**

Remove these functions from `executor.py`:
- `mail_loop()`
- `llm_mail_actions()`
- `initial_mail_messages()`
- `fetch_inbox()`
- `resolve_mail_system()`
- `_mail_schema = build_plan_schema(MAIL_TOOLS)`

Remove these imports that are no longer needed:
- `from actions.mail import refresh_mail, read_emails, move_emails, email_matches, emails_to_text`
- `from tools import MAIL_TOOLS`
- `from tools.schema import build_plan_schema`
- `from config import TARGET_MAILBOX, MAIL_SUMMARY_COUNT`
- `from collections.abc import Callable`

Add new import:
```python
from mail_engine import MailEngine
```

- [ ] **Step 2: Update dispatch_session to use MailEngine.handle() for mail turns**

In `dispatch_session()`, after routing determines `active_agent == "mail"` and the engine exists, bypass the agent pipeline and call `engine.handle()` directly:

```python
def dispatch_session(state, prompt, *, interactive=False, confirm=False):
    # --- Resolve pending confirmation ---
    if state.pending and confirm:
        return resolve_pending(state, interactive=interactive)
    if state.pending and not confirm:
        state.pending = None

    # --- Route via head agent if no active subagent ---
    if not state.active_agent:
        route = _head_agent.route(prompt, state.model)
        state.active_agent = route.agent

    # --- If mail engine exists, delegate directly to it ---
    if state.active_agent == "mail" and state.mail_engine:
        engine = MailEngine.from_dict(state.mail_engine)
        results = engine.handle(prompt, interactive=interactive)
        state.mail_engine = engine.to_dict()
        # Check if session ended
        if any(r["type"] == "done" for r in results):
            state.active_agent = None
            state.mail_engine = None
        # Handle pending confirmations from handle()
        for r in results:
            if r.get("pending"):
                state.pending = r["pending"]
        return results

    # --- Agent calls LLM (normal pipeline) ---
    agent = AGENTS[state.active_agent]
    context = _get_agent_context(state, state.active_agent)
    context.append({"role": "user", "content": prompt})
    plan = agent.plan(context, state.model)

    return dispatch_actions(plan, state, agent, context, interactive=interactive)
```

- [ ] **Step 3: Update dispatch_actions for mail_read (initial fetch)**

Replace the `ActionType.mail_read` case in `dispatch_actions()`. This is only hit on the first mail interaction (before the engine exists):

```python
        elif action.type == ActionType.mail_read:
            engine = MailEngine(model=state.model)
            engine.fetch(count=action.count, unread_only=action.unread_only, account=action.account)
            state.mail_engine = engine.to_dict()
            results.append(engine._mail_list_result(f"Fetched {len(engine.inbox)} emails"))
            context.append({"role": "assistant", "content": action.model_dump_json()})
```

Remove the `ActionType.mail_move` and `ActionType.mail_save` cases from `dispatch_actions()` — these are now handled by `engine.handle()` in subsequent turns.

- [ ] **Step 4: Update resolve_pending for MailEngine**

In `resolve_pending()`, update the `mail_move` case:

```python
    elif action.type == ActionType.mail_move:
        if state.mail_engine:
            engine = MailEngine.from_dict(state.mail_engine)
            msg = engine.execute(action)
            state.mail_engine = engine.to_dict()
            results.append({"type": "mail_move", "content": msg, "agent": "mail"})
        else:
            results.append({"type": "warning", "content": "No mail session active.", "agent": "mail"})
```

Remove the `mail_save` case from `resolve_pending`.

- [ ] **Step 5: Update existing e2e tests**

Update the `_no_mail` fixture and mail tests simultaneously (atomic change):

In `tests/test_e2e.py`, update the `_no_mail` fixture:

```python
@pytest.fixture(autouse=True)
def _no_mail(monkeypatch):
    """Stub out mail backends so tests never hit a real mailbox."""
    monkeypatch.setattr("mail_engine.mail_refresh", lambda: None)
    monkeypatch.setattr("mail_engine.mail_read_emails", lambda *a, **kw: [])
    monkeypatch.setattr("mail_engine.mail_move_by_uids", lambda *a, **kw: 0)
```

Update `TestMailFlow.test_mail_read_fetches_and_replans` — now uses MailEngine, no replan:

```python
    def test_mail_read_fetches_and_displays(self):
        fake_emails = [
            {"uid": 1, "from": "alice@example.com", "subject": "Hello",
             "date": "2026-04-19", "body": "Hi there", "account": "Gmail"},
        ]

        llm = LLMSequence([
            make_route_json("mail", "check email"),
            make_plan_json([
                make_action(ActionType.mail_read, count=5, unread_only=False),
            ]),
            # Recommendation call from MailEngine
            json.dumps({"recommendations": [{"index": 1, "action": "keep"}]}),
        ])
        state = fresh_state()

        with patch("executor.default_adapter", llm), \
             patch("agents.head.default_adapter", llm), \
             patch("agents.base.default_adapter", llm), \
             patch("mail_engine.default_adapter", llm), \
             patch("mail_engine.mail_read_emails", return_value=fake_emails), \
             patch("mail_engine.mail_refresh"), \
             patch("agents.mail.fetch_mailboxes", return_value=[]):
            results = dispatch_session(state, "check my email")

        types = [r["type"] for r in results]
        assert "mail_list" in types
        assert state.mail_engine is not None
```

- [ ] **Step 6: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add executor.py tests/test_e2e.py
git commit -m "feat: wire MailEngine into executor, replace mail_loop"
```

---

### Task 11: Wire MailEngine into CLI

**Files:**
- Modify: `cli.py`

- [ ] **Step 1: Remove MAIL_SYSTEM prompt and old mail setup from cli.py**

Remove the `MAIL_SYSTEM` variable entirely. Remove `build_mail_system` function if it exists. Remove imports no longer needed: `fetch_mailboxes`, `load_memory`, `TARGET_MAILBOX`, `MAIL_SUMMARY_COUNT`.

Add multi-account selection: when the mail agent is activated and multiple IMAP accounts exist, prompt the user to choose before the first fetch. Store the choice on the engine via `state.mail_engine`.

The `execute()` function in `executor.py` that handled stateless mail via `mail_loop()` should now route mail through `dispatch_session()` with an auto-created session. Update the CLI chat command:

```python
@app.command()
def chat(
    prompt: str,
    model: str = DEFAULT_MODEL,
    session: Optional[str] = None,
):
    """Send a prompt to the agent."""
    # Mail always uses a persistent session
    sid = session or "default"
    state = load_session(sid, model)
    results = dispatch_session(state, prompt, interactive=True)
    save_session(state)

    for r in results:
        rtype = r["type"]
        if rtype == "done":
            print("[done] session ended.", flush=True)
        elif rtype == "mail_list":
            print(r["content"], flush=True)
        elif rtype == "confirm":
            import typer as t
            if t.confirm(r["content"]):
                results2 = dispatch_session(state, "", interactive=True, confirm=True)
                save_session(state)
                for r2 in results2:
                    print(r2.get("content", ""), flush=True)
        elif rtype in ("answer", "summary", "warning", "ask_user", "mail_move", "output"):
            print(r.get("content", ""), flush=True)

    # Interactive mail loop: keep prompting if mail agent is active
    while state.active_agent == "mail" and not any(r["type"] == "done" for r in results):
        user_input = typer.prompt("\n> ")
        if user_input.lower() in ("done", "exit", "quit"):
            print("[done] mail session ended.", flush=True)
            break
        results = dispatch_session(state, user_input, interactive=True)
        save_session(state)
        for r in results:
            rtype = r["type"]
            if rtype == "done":
                print("[done] session ended.", flush=True)
                break
            elif rtype == "mail_list":
                print(r["content"], flush=True)
            elif rtype == "confirm":
                import typer as t
                if t.confirm(r["content"]):
                    results2 = dispatch_session(state, "", interactive=True, confirm=True)
                    save_session(state)
                    for r2 in results2:
                        print(r2.get("content", ""), flush=True)
                        # Redisplay after mail action
                        if r2["type"] == "mail_move" and state.mail_engine:
                            from mail_engine import MailEngine
                            engine = MailEngine.from_dict(state.mail_engine)
                            print(engine.display(), flush=True)
            elif rtype in ("answer", "summary", "warning", "ask_user", "mail_move", "output"):
                print(r.get("content", ""), flush=True)
```

- [ ] **Step 2: Remove the old stateless `execute()` function from executor.py if not used elsewhere**

Check if `execute()` is imported anywhere other than `cli.py`. If only used by CLI, remove it from executor.py. Keep `dispatch_session` as the single entry point.

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add cli.py executor.py
git commit -m "feat: wire MailEngine into CLI, remove old mail_loop path"
```

---

### Task 12: Update server.py for structured mail responses

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add structured fields to ActionResponse**

```python
class ActionResponse(BaseModel):
    type: str
    content: str
    agent: str | None = None
    pending_confirm: str | None = None
    # Structured mail data for frontend
    emails: list[dict] | None = None
    page: int | None = None
    total_pages: int | None = None
    total_emails: int | None = None
```

- [ ] **Step 2: Update the chat endpoint to pass through structured data**

```python
@app.post("/chat", response_model=list[ActionResponse])
def chat(req: ChatRequest):
    if req.session_id:
        state = load_session(req.session_id, req.model)
        results = dispatch_session(state, req.prompt, interactive=False, confirm=req.confirm)
        save_session(state)
    else:
        state = SessionState(session_id="_stateless", model=req.model)
        results = dispatch_session(state, req.prompt)

    return [
        ActionResponse(
            type=r["type"],
            content=r["content"],
            agent=r.get("agent"),
            pending_confirm=r.get("pending_confirm"),
            emails=r.get("emails"),
            page=r.get("page"),
            total_pages=r.get("total_pages"),
            total_emails=r.get("total_emails"),
        )
        for r in results
    ]
```

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat: add structured mail fields to ActionResponse for frontend"
```

---

### Task 13: Update mail agent system prompt

**Files:**
- Modify: `agents/mail.py`
- Modify: `tools/registry.py` (update MAIL_SAVE → remove, already done if applicable)

- [ ] **Step 1: Simplify the mail agent to intent-parser role**

```python
# agents/mail.py
from .base import AgentDef
from memory import load_memory
from tools import MAIL_TOOLS, build_system_prompt


class MailAgent(AgentDef):
    name = "mail"
    tools = MAIL_TOOLS

    def system_prompt(self) -> str:
        return build_system_prompt(
            role=(
                "an email intent parser. You receive the user's command and the current "
                "email list. Return a plan of actions as JSON. Use indices (1-based) to "
                "reference specific emails. For deletes, use mail_move with folder='Trash'. "
                "For reading an email, use answer with the index. For fetching more, use mail_read. "
                "You do NOT generate display text — only structured actions."
            ),
            tools=self.tools,
            memory=load_memory("mail"),
        )
```

Note: the `context={"Available mailboxes": fetch_mailboxes()}` is removed because the engine handles mailbox resolution, not the LLM.

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add agents/mail.py
git commit -m "feat: simplify mail agent to intent-parser role"
```

---

### Task 14: Update tools/schema.py for indices field

**Files:**
- Modify: `tools/schema.py`

- [ ] **Step 1: Add indices field to the restricted Action model**

In `build_plan_schema()`, add `indices` to the model and fix `folder` default to match `action.py` (`"Trash"` not `"Archive"`):

```python
    RestrictedAction = create_model(
        "Action",
        type=(RestrictedActionType, ...),
        content=(str, ""),
        count=(int, 10),
        unread_only=(bool, False),
        folder=(str, "Trash"),       # was "Archive" — align with action.py
        filter_from=(str, ""),
        filter_subject=(str, ""),
        account=(str, ""),
        indices=(list[int], []),
        continue_conversation=(bool, False),
    )
```

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tools/schema.py
git commit -m "feat: add indices to restricted Action schema"
```

---

### Task 15: Final integration test

**Files:**
- Modify: `tests/test_mail_engine.py`

- [ ] **Step 1: Write a full flow integration test**

Append to `tests/test_mail_engine.py`:

```python
class TestFullFlow:
    """End-to-end: fetch → recommend → user action → execute → redisplay."""

    def test_fetch_recommend_delete_redisplay(self):
        fake_emails = [
            {"uid": 1, "from": "spam@test.com", "subject": "Buy now", "date": "2026-04-19", "body": "Promo", "account": "Gmail"},
            {"uid": 2, "from": "boss@test.com", "subject": "Meeting", "date": "2026-04-19", "body": "At 3pm", "account": "Gmail"},
        ]

        rec_response = json.dumps({
            "recommendations": [
                {"index": 1, "action": "delete"},
                {"index": 2, "action": "keep"},
            ]
        })

        delete_plan = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1], folder="Trash")
        ]).model_dump_json()

        engine = MailEngine(model="test")

        # Step 1: Fetch + recommend
        with patch("mail_engine.mail_read_emails", return_value=fake_emails), \
             patch("mail_engine.mail_refresh"), \
             patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = rec_response
            engine.fetch()

        assert len(engine.inbox) == 2
        assert engine.inbox[0]["recommendation"] == "delete"
        assert engine.inbox[1]["recommendation"] == "keep"

        # Step 2: Display — deterministic, no LLM
        display = engine.display()
        assert "spam@test.com" in display or "Buy now" in display
        assert "[delete]" in display
        assert "[keep]" in display

        # Step 3: User says "delete 1" → parse intent
        with patch("mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = delete_plan
            plan = engine.parse_intent("delete 1")

        assert plan.actions[0].indices == [1]

        # Step 4: Execute
        with patch("mail_engine.mail_move_by_uids", return_value=1):
            result = engine.execute(plan.actions[0])

        assert "Deleted 1" in result
        assert len(engine.inbox) == 1

        # Step 5: Redisplay — deterministic, no LLM
        display = engine.display()
        assert "Buy now" not in display  # deleted email gone
        assert "Meeting" in display      # remaining email present
        assert "[keep]" in display
```

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_mail_engine.py
git commit -m "test: add full flow integration test for MailEngine"
```

---

### Task 16: Clean up and update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: Update CLAUDE.md**

Add `mail_engine.py` to the architecture section. Update the "Key constraints" to mention the hybrid approach. Remove references to `mail_loop`.

- [ ] **Step 2: Update ARCHITECTURE.md**

Update the component diagram to show `MailEngine` as a new component between agents and external systems. Update the mail flow section.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md ARCHITECTURE.md
git commit -m "docs: update architecture docs for MailEngine redesign"
```

- [ ] **Step 4: Run full test suite one final time**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS
