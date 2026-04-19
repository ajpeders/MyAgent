from .mail import MailAgent
from .command import CommandAgent
from .answer import AnswerAgent

# Registry: agent name → system prompt builder
AGENTS: dict[str, "AgentDef"] = {
    "mail":    MailAgent(),
    "command": CommandAgent(),
    "answer":  AnswerAgent(),
}
