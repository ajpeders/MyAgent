"""End-to-end tests for the agent dispatch pipeline.

Mocks the LLM adapter at the boundary so everything downstream
(routing → agent.plan → _dispatch_plan → state) runs for real.

Session state is minimal: only mail_engine persists. Routing and model
are per-request. No active_agent, contexts, or pending in state.
"""
import json
from unittest.mock import patch

import pytest

from core.actions.action import Action, ActionType, Plan, AgentRoute
from core.session_store import SessionState
from core.executor import dispatch_session


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_route_json(agent: str, intent: str = "") -> str:
    return AgentRoute(agent=agent, intent=intent).model_dump_json()


def make_plan_json(actions: list[Action]) -> str:
    return Plan(actions=actions).model_dump_json()


def make_action(type: ActionType, **kwargs) -> Action:
    return Action(type=type, **kwargs)


def fresh_state(session_id: str = "test") -> SessionState:
    return SessionState(session_id=session_id, user_id="test-user")


MODEL = "test-model"


class LLMSequence:
    """Mock adapter returning a sequence of predetermined responses."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._call_count = 0

    def complete(self, messages, schema, model):
        assert self._call_count < len(self._responses), (
            f"LLM called {self._call_count + 1}x but only {len(self._responses)} responses provided"
        )
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp

    @property
    def call_count(self):
        return self._call_count


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("core.memory.MEMORY_DIR", tmp_path / "memory")
    (tmp_path / "memory").mkdir()


@pytest.fixture(autouse=True)
def _no_mail(monkeypatch):
    monkeypatch.setattr("core.mail_engine.mail_refresh", lambda: None)
    monkeypatch.setattr("core.mail_engine.mail_read_emails", lambda *a, **kw: [])
    monkeypatch.setattr("core.mail_engine.mail_move_by_uids", lambda *a, **kw: 0)


# ── Tests: Routing ───────────────────────────────────────────────────────────


class TestRouting:
    def test_routes_to_answer_agent(self):
        llm = LLMSequence([
            make_route_json("answer", "general question"),
            make_plan_json([make_action(ActionType.answer, content="Hello!")]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "hello", MODEL)

        assert any(r["type"] == "answer" for r in results)

    def test_routes_to_mail_agent(self):
        llm = LLMSequence([
            make_route_json("mail", "check email"),
            # MailEngine recommend() call
            json.dumps({"recommendations": []}),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.mail_engine.default_adapter", llm):
            results = dispatch_session(state, "check my email", MODEL)

        assert state.mail_engine is not None
        assert any(r["type"] == "mail_list" for r in results)

    def test_routes_to_command_agent(self):
        llm = LLMSequence([
            make_route_json("command", "run a command"),
            make_plan_json([make_action(ActionType.answer, content="What command?")]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "run ls", MODEL)

        assert any(r["type"] == "answer" for r in results)


# ── Tests: Answer agent ──────────────────────────────────────────────────────


class TestAnswerFlow:
    def test_simple_answer(self):
        llm = LLMSequence([
            make_route_json("answer"),
            make_plan_json([make_action(ActionType.answer, content="Paris.")]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "Capital of France?", MODEL)

        assert results[0] == {"type": "answer", "content": "Paris.", "agent": "answer"}

    def test_ask_user_stops_plan(self):
        llm = LLMSequence([
            make_route_json("answer"),
            make_plan_json([
                make_action(ActionType.ask_user, content="Could you clarify?"),
                make_action(ActionType.answer, content="Never reached."),
            ]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "do something", MODEL)

        assert len(results) == 1
        assert results[0]["type"] == "ask_user"

    def test_done_stops_plan(self):
        llm = LLMSequence([
            make_route_json("answer"),
            make_plan_json([
                make_action(ActionType.answer, content="Bye!"),
                make_action(ActionType.done),
            ]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "goodbye", MODEL)

        assert any(r["type"] == "done" for r in results)


# ── Tests: Command agent ─────────────────────────────────────────────────────


class TestCommandFlow:
    def test_command_returns_confirmation_in_non_interactive(self):
        llm = LLMSequence([
            make_route_json("command"),
            make_plan_json([make_action(ActionType.command, content="ls -la")]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "list files", MODEL)

        assert results[0]["type"] == "confirm"
        assert results[0]["content"] == "ls -la"


# ── Tests: Mail flow ─────────────────────────────────────────────────────────


class TestMailFlow:
    def test_mail_routes_create_engine(self):
        """Routing to mail fetches inbox and creates mail_engine in session."""
        llm = LLMSequence([
            make_route_json("mail"),
            json.dumps({"recommendations": []}),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.mail_engine.default_adapter", llm):
            results = dispatch_session(state, "check my email", MODEL)

        assert state.mail_engine is not None
        assert any(r["type"] == "mail_list" for r in results)

    def test_second_mail_turn_uses_engine(self):
        """Once mail_engine exists, subsequent turns go directly to MailEngine."""
        fake_emails = [
            {"uid": 1, "from": "alice@test.com", "subject": "Hi", "date": "2026-04-19", "body": "Hello", "account": "Gmail"},
        ]
        # Turn 1: route → fetch → engine created
        llm1 = LLMSequence([
            make_route_json("mail"),
            json.dumps({"recommendations": [{"index": 1, "action": "keep"}]}),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm1), \
             patch("core.agents.head.default_adapter", llm1), \
             patch("core.mail_engine.default_adapter", llm1), \
             patch("core.mail_engine.mail_read_emails", return_value=fake_emails):
            dispatch_session(state, "check email", MODEL)

        assert state.mail_engine is not None

        # Turn 2: no routing — goes straight to MailEngine.handle()
        delete_plan = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1], folder="Trash")
        ]).model_dump_json()
        llm2 = LLMSequence([delete_plan])

        with patch("core.mail_engine.default_adapter", llm2):
            results = dispatch_session(state, "delete 1", MODEL)

        # MailEngine returns confirm (non-interactive mode)
        assert results[0]["type"] == "confirm"
        assert llm2.call_count == 1  # only MailEngine.parse_intent(), no routing

    def test_mail_done_clears_engine(self):
        """A 'done' result from MailEngine clears the session engine."""
        state = fresh_state()
        state.mail_engine = {"inbox": [], "page": 0, "model": MODEL, "page_size": 20, "account": ""}

        done_plan = Plan(actions=[Action(type=ActionType.done)]).model_dump_json()
        llm = LLMSequence([done_plan])

        with patch("core.mail_engine.default_adapter", llm):
            results = dispatch_session(state, "done", MODEL)

        assert any(r["type"] == "done" for r in results)
        assert state.mail_engine is None


# ── Tests: Memory actions ────────────────────────────────────────────────────


class TestMemoryActions:
    def test_remember_saves_to_memory(self):
        llm = LLMSequence([
            make_route_json("answer"),
            make_plan_json([make_action(ActionType.remember, content="User prefers dark mode")]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "I prefer dark mode", MODEL)

        assert results[0]["type"] == "remember"
        assert "dark mode" in results[0]["content"]

    def test_note_returns_note_type(self):
        llm = LLMSequence([
            make_route_json("answer"),
            make_plan_json([make_action(ActionType.note, content="Meeting at 3pm")]),
        ])
        state = fresh_state()

        with patch("core.executor.default_adapter", llm), \
             patch("core.agents.head.default_adapter", llm), \
             patch("core.agents.base.default_adapter", llm):
            results = dispatch_session(state, "note: meeting at 3pm", MODEL)

        assert results[0]["type"] == "note"
