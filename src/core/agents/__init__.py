from .mail import MailAgent
from .command import CommandAgent
from .answer import AnswerAgent
from .core import CoreAgent

# Registry: agent name → system prompt builder
AGENTS: dict[str, "AgentDef"] = {
    "mail":    MailAgent(),
    "command": CommandAgent(),
    "answer":  AnswerAgent(),
    "core":    CoreAgent(),
}
