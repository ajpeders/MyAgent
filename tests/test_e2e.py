"""End-to-end tests for the agent dispatch pipeline.

Tests the new AgentExecutor-based dispatch_session which:
  1. Routes via HeadAgent (uses default_adapter.complete_sync)
  2. Runs AgentExecutor (uses LLMService.chat -> async tool loop)
  3. Returns [{"type": "answer", "content": ..., "agent": ...}]

The old plan-based dispatch (Action/Plan types) is replaced by the
tool-calling executor. dispatch_session always returns answer-type results.
"""
import json
from unittest.mock import patch, AsyncMock

import pytest

from src.core.actions.action import AgentRoute
from src.core.executor import dispatch_session
from src.gateway.session import SessionState


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_route_json(agent: str, intent: str = "") -> str:
    return AgentRoute(agent=agent, intent=intent).model_dump_json()


def fresh_state(session_id: str = "test") -> SessionState:
    return SessionState(session_id=session_id, user_id="test-user")


MODEL = "test-model"


class LLMSequence:
    """Mock adapter returning a sequence of predetermined responses.

    Supports both the adapter interface (complete_sync) and the async
    LLMService interface (chat) for AgentExecutor compatibility.
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._call_count = 0

    def _next(self):
        assert self._call_count < len(self._responses), (
            f"LLM called {self._call_count + 1}x but only {len(self._responses)} responses provided"
        )
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp

    def complete(self, messages, schema, model):
        return self._next()

    def complete_sync(self, messages, schema, model):
        return self._next()

    async def chat(self, messages, tools, model):
        """AgentExecutor calls this. Returns content (no tool_calls)."""
        content = self._next()
        return {"content": content}

    @property
    def call_count(self):
        return self._call_count


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.memory.MEMORY_DIR", tmp_path / "memory")
    (tmp_path / "memory").mkdir()


@pytest.fixture(autouse=True)
def _no_mail(monkeypatch):
    monkeypatch.setattr("src.core.mail_engine.mail_refresh", lambda: None)
    monkeypatch.setattr("src.core.mail_engine.mail_read_emails", lambda *a, **kw: [])
    monkeypatch.setattr("src.core.mail_engine.mail_move_by_uids", lambda *a, **kw: 0)


# ── Tests: Routing ───────────────────────────────────────────────────────────


class TestRouting:
    def test_routes_to_answer_agent(self):
        llm = LLMSequence([
            make_route_json("answer", "general question"),
            "Hello!",  # AgentExecutor returns this as content
        ])
        state = fresh_state()

        with patch("src.core.executor.LLMService", return_value=llm), \
             patch("src.core.agents.head.default_adapter", llm):
            results = dispatch_session(state, "hello", MODEL)

        assert results[0]["type"] == "answer"
        assert results[0]["agent"] == "answer"
        assert results[0]["content"] == "Hello!"

    def test_routes_to_command_agent(self):
        llm = LLMSequence([
            make_route_json("command", "run a command"),
            "I can help you run commands.",
        ])
        state = fresh_state()

        with patch("src.core.executor.LLMService", return_value=llm), \
             patch("src.core.agents.head.default_adapter", llm):
            results = dispatch_session(state, "run ls", MODEL)

        assert results[0]["type"] == "answer"
        assert results[0]["agent"] == "command"

    def test_routes_to_mail_agent(self):
        llm = LLMSequence([
            make_route_json("mail", "check email"),
            "Checking your email...",
        ])
        state = fresh_state()

        with patch("src.core.executor.LLMService", return_value=llm), \
             patch("src.core.agents.head.default_adapter", llm):
            results = dispatch_session(state, "check my email", MODEL)

        assert results[0]["type"] == "answer"
        assert results[0]["agent"] == "mail"


# ── Tests: Answer agent ──────────────────────────────────────────────────────


class TestAnswerFlow:
    def test_simple_answer(self):
        llm = LLMSequence([
            make_route_json("answer"),
            "Paris.",
        ])
        state = fresh_state()

        with patch("src.core.executor.LLMService", return_value=llm), \
             patch("src.core.agents.head.default_adapter", llm):
            results = dispatch_session(state, "Capital of France?", MODEL)

        assert results[0] == {"type": "answer", "content": "Paris.", "agent": "answer"}

    def test_agent_name_preserved_in_result(self):
        """dispatch_session preserves which agent was routed to."""
        llm = LLMSequence([
            make_route_json("command"),
            "Running command...",
        ])
        state = fresh_state()

        with patch("src.core.executor.LLMService", return_value=llm), \
             patch("src.core.agents.head.default_adapter", llm):
            results = dispatch_session(state, "list files", MODEL)

        assert results[0]["agent"] == "command"


# ── Tests: Head agent routing accuracy ───────────────────────────────────────


class TestHeadAgent:
    def test_route_parses_agent_and_intent(self):
        from src.core.agents.head import HeadAgent

        route_json = make_route_json("mail", "user wants email")
        llm = LLMSequence([route_json])

        with patch("src.core.agents.head.default_adapter", llm):
            head = HeadAgent()
            route = head.route("check my email", MODEL)

        assert route.agent == "mail"
        assert route.intent == "user wants email"

    def test_route_calls_llm_once(self):
        llm = LLMSequence([make_route_json("answer")])

        with patch("src.core.agents.head.default_adapter", llm):
            from src.core.agents.head import HeadAgent
            HeadAgent().route("hello", MODEL)

        assert llm.call_count == 1


# ── Tests: Session state ────────────────────────────────────────────────────


class TestSessionState:
    def test_dispatch_preserves_session_identity(self):
        llm = LLMSequence([
            make_route_json("answer"),
            "ok",
        ])
        state = fresh_state("my-session")

        with patch("src.core.executor.LLMService", return_value=llm), \
             patch("src.core.agents.head.default_adapter", llm):
            dispatch_session(state, "hello", MODEL)

        # State object is preserved through dispatch
        assert state.session_id == "my-session"
        assert state.user_id == "test-user"
