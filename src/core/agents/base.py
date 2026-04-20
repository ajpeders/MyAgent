"""Base class for subagents."""
from abc import ABC, abstractmethod

from core.actions.action import Plan
from core.llm import default_adapter
from core.tools.defs import ToolDef
from core.tools.schema import build_plan_schema


class AgentDef(ABC):
    name: str
    tools: list[ToolDef]  # declares which tools this agent can use

    @abstractmethod
    def system_prompt(self) -> str: ...

    def plan(self, messages: list[dict], model: str) -> Plan:
        """Call LLM with this agent's scoped schema and return a Plan."""
        schema = build_plan_schema(self.tools)
        content = default_adapter.complete(messages, schema, model)
        return Plan.model_validate_json(content)
