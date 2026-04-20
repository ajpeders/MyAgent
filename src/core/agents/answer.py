from .base import AgentDef
from core.memory import load_memory
from core.tools import ANSWER_TOOLS, build_system_prompt


class AnswerAgent(AgentDef):
    name = "answer"
    tools = ANSWER_TOOLS

    def system_prompt(self) -> str:
        return build_system_prompt(
            role="a helpful assistant that answers questions and manages notes and preferences",
            tools=self.tools,
            memory=load_memory("answer"),
        )
