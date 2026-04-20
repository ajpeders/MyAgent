import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cli.__main__ as cli
from core import executor
from core.actions.action import Action, ActionType
from core.actions.mail import emails_to_text
from core.config import TARGET_MAILBOX
from core.session_store import SessionState


class CliPromptTests(unittest.TestCase):
    @patch("cli.__main__.load_memory", return_value=["remember invoices", "prefer concise replies"])
    def test_build_messages_includes_memory(self, _load_memory):
        messages = cli.build_messages("summarize my tasks")

        self.assertEqual(messages[1], {"role": "user", "content": "summarize my tasks"})
        system = messages[0]["content"]
        self.assertIn("Memory:\n- remember invoices\n- prefer concise replies", system)

    def test_legacy_mail_system_prompt_removed(self):
        self.assertFalse(hasattr(cli, "build_mail_system"))

    def test_emails_to_text_includes_structured_fields(self):
        text = emails_to_text([
            {"from": "a@example.com", "subject": "hello", "date": "today"},
            {"from": "b@example.com", "subject": "world", "date": "tomorrow"},
        ])

        self.assertIn("1. FROM: a@example.com", text)
        self.assertIn("SUBJECT: hello", text)
        self.assertIn("DATE: today", text)
        self.assertIn("---", text)
        self.assertIn("2. FROM: b@example.com", text)

    @patch("cli.__main__.fetch_mailboxes", return_value=["Gmail / Inbox", "Gmail / Archive"])
    def test_mailboxes_command_prints_configured_and_available(self, _fetch_mailboxes):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            cli.mailboxes()

        output = stdout.getvalue()
        self.assertIn(f"Configured source mailbox: {TARGET_MAILBOX}", output)
        self.assertIn("- Gmail / Inbox", output)

    @patch("cli.__main__.save_session")
    @patch("cli.__main__.dispatch_session", return_value=[{"type": "answer", "content": "hi", "agent": "answer"}])
    @patch("cli.__main__.load_session")
    def test_chat_uses_default_session_when_session_omitted(self, load_session, _dispatch, _save):
        state = SessionState(session_id=cli.DEFAULT_SESSION_ID, user_id="u1")
        load_session.return_value = state

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            cli.chat("hello", model="test-model", session=None)

        load_session.assert_called_once_with(cli.DEFAULT_SESSION_ID)
        self.assertIn("hi", stdout.getvalue())

    @patch("cli.__main__.save_session")
    @patch("cli.__main__.dispatch_session", return_value=[{"type": "answer", "content": "hi", "agent": "answer"}])
    @patch("cli.__main__.load_session")
    def test_chat_uses_explicit_session_when_provided(self, load_session, _dispatch, _save):
        state = SessionState(session_id="work", user_id="u1")
        load_session.return_value = state

        with redirect_stdout(io.StringIO()):
            cli.chat("hello", model="test-model", session="work")

        load_session.assert_called_once_with("work")


class ExecutorTests(unittest.TestCase):
    @patch("core.executor.typer.confirm")
    @patch("core.executor.run_in_docker", return_value="hello from sandbox")
    def test_execute_runs_command_and_stops(self, _run_in_docker, _confirm):
        with patch("core.executor.default_adapter") as mock_llm:
            mock_llm.complete.return_value = Action(type=ActionType.command, content="echo hello").model_dump_json()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                executor.execute([{"role": "system", "content": "test system"}], "test-model")

        self.assertIn("[output] hello from sandbox", stdout.getvalue())

    @patch("core.executor.mail_loop")
    def test_execute_delegates_mail_to_mail_loop(self, mail_loop):
        with patch("core.executor.default_adapter") as mock_llm:
            mock_llm.complete.return_value = Action(type=ActionType.mail_read, count=5, unread_only=True).model_dump_json()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                executor.execute([{"role": "system", "content": "test system"}], "test-model")

        mail_loop.assert_called_once()

    def test_execute_prints_misc(self):
        with patch("core.executor.default_adapter") as mock_llm:
            mock_llm.complete.return_value = Action(type=ActionType.misc, content="No matching action.").model_dump_json()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                executor.execute([{"role": "system", "content": "test system"}], "test-model")

        self.assertIn("[misc] No matching action.", stdout.getvalue())

    @patch("core.executor.read_emails", return_value=[{"from": "a@example.com", "subject": "hello"}])
    @patch("core.executor.refresh_mail")
    def test_fetch_inbox_returns_emails(self, _refresh_mail, _read_emails):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            inbox, label = executor.fetch_inbox(Action(type=ActionType.mail_read, count=1, unread_only=True))

        self.assertEqual(label, "unread")
        self.assertEqual(inbox, [{"from": "a@example.com", "subject": "hello"}])


if __name__ == "__main__":
    unittest.main()
