import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch, MagicMock

import cli
import executor
from actions.action import Action, ActionType, Plan
from actions.mail import emails_to_text
from config import TARGET_MAILBOX, MAIL_SUMMARY_COUNT
from session_store import SessionState


class CliPromptTests(unittest.TestCase):
    @patch("cli.load_memory", return_value=["remember invoices", "prefer concise replies"])
    def test_build_messages_includes_memory_without_mailboxes(self, _load_memory):
        messages = cli.build_messages("summarize my tasks")

        self.assertEqual(messages[1], {"role": "user", "content": "summarize my tasks"})
        system = messages[0]["content"]
        self.assertIn("Memory:\n- remember invoices\n- prefer concise replies", system)
        self.assertNotIn("Available mailboxes:", system)

    @patch("cli.fetch_mailboxes", return_value=["Archive", "Saved"])
    @patch("cli.load_memory", return_value=["likes email summaries"])
    def test_build_mail_system_includes_source_and_destinations(self, _load_memory, _fetch_mailboxes):
        system = cli.build_mail_system()

        self.assertIn(f"Source mailbox:\n- {TARGET_MAILBOX}", system)
        self.assertIn("Available destination mailboxes:\n- Archive\n- Saved", system)
        self.assertIn(f"top {MAIL_SUMMARY_COUNT} email subjects", system)
        self.assertIn("Memory:\n- likes email summaries", system)

    def test_emails_to_text_includes_only_subjects(self):
        self.assertEqual(
            emails_to_text([{"subject": "hello"}, {"subject": "world"}]),
            "SUBJECT: hello\n---\nSUBJECT: world",
        )

    @patch("cli.fetch_mailboxes", return_value=["Gmail / Inbox", "Gmail / Archive", "On My Mac / Saved"])
    def test_mailboxes_command_prints_configured_and_available_mailboxes(self, _fetch_mailboxes):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            cli.mailboxes()

        output = stdout.getvalue()
        self.assertIn(f"Configured source mailbox: {TARGET_MAILBOX}", output)
        self.assertIn("Mailboxes:", output)
        self.assertIn("- Gmail / Inbox", output)
        self.assertIn("- Gmail / Archive", output)
        self.assertIn("- On My Mac / Saved", output)


class ExecutorTests(unittest.TestCase):
    @patch("executor.typer.confirm")
    @patch("executor.run_in_docker", return_value="hello from sandbox")
    def test_execute_runs_command_and_stops(self, _run_in_docker, _confirm):
        with patch("executor.llm_action", return_value=Action(type=ActionType.command, content="echo hello")):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                executor.execute([{"role": "system", "content": "test system"}], "test-model", "mail system")

        output = stdout.getvalue()
        self.assertIn("[output] hello from sandbox", output)
        self.assertIn("[thinking] agent...", output)

    def test_dispatch_actions_returns_answer(self):
        plan = Plan(actions=[Action(type=ActionType.answer, content="4")])
        state = SessionState(session_id="test", model="test-model", active_agent="answer")
        agent = MagicMock()
        agent.name = "answer"
        context = [{"role": "system", "content": "test system"}]

        results = executor.dispatch_actions(plan, state, agent, context)

        self.assertEqual(results, [{"type": "answer", "content": "4", "agent": "answer"}])

    def test_dispatch_actions_returns_confirm_for_command(self):
        plan = Plan(actions=[Action(type=ActionType.command, content="echo hello")])
        state = SessionState(session_id="test", model="test-model", active_agent="command")
        agent = MagicMock()
        agent.name = "command"
        context = [{"role": "system", "content": "test system"}]

        results = executor.dispatch_actions(plan, state, agent, context, interactive=False)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "confirm")
        self.assertEqual(results[0]["content"], "echo hello")
        self.assertIsNotNone(state.pending)

    @patch("executor._head_agent")
    def test_dispatch_session_routes_via_head_agent(self, mock_head):
        from actions.action import AgentRoute
        mock_head.route.return_value = AgentRoute(agent="answer", intent="test")

        state = SessionState(session_id="test", model="test-model")
        agent = MagicMock()
        agent.name = "answer"
        agent.system_prompt.return_value = "You are a test agent."
        agent.plan.return_value = Plan(actions=[Action(type=ActionType.answer, content="hi")])

        with patch.dict(executor.AGENTS, {"answer": agent}):
            results = executor.dispatch_session(state, "hello")

        mock_head.route.assert_called_once_with("hello", "test-model")
        self.assertEqual(state.active_agent, "answer")
        self.assertEqual(results, [{"type": "answer", "content": "hi", "agent": "answer"}])

    @patch("executor.mail_loop")
    def test_execute_delegates_mail_to_mail_loop(self, mail_loop):
        with patch("executor.llm_action", return_value=Action(type=ActionType.mail_read, count=5, unread_only=True)):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                executor.execute([{"role": "system", "content": "test system"}], "test-model", "mail system")

        mail_loop.assert_called_once()
        self.assertIn("[thinking] agent...", stdout.getvalue())

    def test_execute_prints_misc(self):
        with patch("executor.llm_action", return_value=Action(type=ActionType.misc, content="No matching action.")):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                executor.execute([{"role": "system", "content": "test system"}], "test-model", "mail system")

        self.assertIn("[misc] No matching action.", stdout.getvalue())
        self.assertIn("[thinking] agent...", stdout.getvalue())

    @patch("executor.read_emails", return_value=[{"from": "a@example.com", "subject": "hello"}])
    @patch("executor.refresh_mail")
    def test_fetch_inbox_prints_mail_status(self, _refresh_mail, _read_emails):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            inbox, label = executor.fetch_inbox(Action(type=ActionType.mail_read, count=1, unread_only=True))

        self.assertEqual(label, "unread")
        self.assertEqual(inbox, [{"from": "a@example.com", "subject": "hello"}])
        self.assertIn("[mail] getting mail...", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
