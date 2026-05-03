from .base import AgentDef
from src.core.tools import COMMAND_TOOLS, build_system_prompt


class CommandAgent(AgentDef):
    name = "command"
    tools = COMMAND_TOOLS

    def system_prompt(self, **kwargs) -> str:
        return build_system_prompt(
            role="a command execution assistant that runs shell commands safely",
            tools=self.tools,
            context={"Sandbox": ["Commands run in an isolated Docker container, never on the host machine."]},
        )
