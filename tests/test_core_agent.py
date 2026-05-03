"""Tests for CoreAgent definition and HeadAgent routing updates."""
import pytest

from src.core.agents.core import CoreAgent
from src.core.agents import AGENTS
from src.core.agents.head import _AGENT_CONTEXT, _ROUTE_TOOL


class TestCoreAgent:
    def test_has_10_tools(self):
        agent = CoreAgent()
        assert len(agent.tools) == 10

    def test_tool_names(self):
        agent = CoreAgent()
        names = [t.name for t in agent.tools]
        assert "search_news" in names
        assert "get_curated" in names
        assert "get_calendar" in names
        assert "get_mail_summary" in names
        assert "get_memories" in names
        assert "get_profile" in names
        assert "create_calendar_event" in names
        assert "answer" in names
        assert "remember" in names
        assert "done" in names

    def test_system_prompt_contains_personal_agent(self):
        agent = CoreAgent()
        prompt = agent.system_prompt()
        assert "personal agent" in prompt

    def test_system_prompt_contains_tool_names(self):
        agent = CoreAgent()
        prompt = agent.system_prompt()
        assert "search_news" in prompt
        assert "get_calendar" in prompt

    def test_system_prompt_with_user_id(self, monkeypatch):
        from src.services.profile.models import ContextSnapshot

        fake = ContextSnapshot(
            user_id="u1",
            interests=["tech"],
            recent_signals=[],
            calendar_today=[],
            calendar_upcoming=[],
            mail_subjects=[],
            memories=[],
        )
        monkeypatch.setattr(
            "src.services.profile.service.ProfileService.context_snapshot",
            lambda self, uid: fake,
        )
        agent = CoreAgent()
        prompt = agent.system_prompt(user_id="u1")
        assert "personal agent" in prompt
        assert "tech" in prompt

    def test_system_prompt_handles_profile_error(self, monkeypatch):
        def _boom(self, uid):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.services.profile.service.ProfileService.context_snapshot", _boom,
        )
        agent = CoreAgent()
        prompt = agent.system_prompt(user_id="u1")
        assert "personal agent" in prompt
        assert "Context unavailable" in prompt


class TestAgentsRegistry:
    def test_core_in_agents(self):
        assert "core" in AGENTS
        assert isinstance(AGENTS["core"], CoreAgent)


class TestHeadAgentRouting:
    def test_agent_context_includes_core(self):
        agents_list = _AGENT_CONTEXT["Available agents"]
        core_entry = [a for a in agents_list if a.startswith("core")]
        assert len(core_entry) == 1
        assert "personal context" in core_entry[0]

    def test_route_tool_mentions_core(self):
        agent_param = next(p for p in _ROUTE_TOOL.params if p.name == "agent")
        assert "core" in agent_param.description
