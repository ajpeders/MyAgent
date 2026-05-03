"""Core agent — personal assistant with full context access."""
from .base import AgentDef
from src.core.tools.registry import CORE_TOOLS
from src.core.tools.prompt import build_system_prompt


class CoreAgent(AgentDef):
    name = "core"
    tools = CORE_TOOLS

    def system_prompt(self, **kwargs) -> str:
        user_id = kwargs.get("user_id", "")
        context = None
        if user_id:
            try:
                from src.services.profile.service import ProfileService

                snapshot = ProfileService().context_snapshot(user_id)
                context = {
                    "User context": [snapshot.model_dump_json(indent=2)],
                }
            except Exception:
                context = {"User context": ["Context unavailable"]}
        return build_system_prompt(
            role="the user's personal agent. You know their interests, schedule, email, and stored memories. Use your tools to answer questions grounded in real data — never guess or use stale info.",
            tools=self.tools,
            context=context,
        )
