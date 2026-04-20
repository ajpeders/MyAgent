from .base import AgentDef
from core.actions.mail import fetch_mailboxes
from core.memory import load_memory
from core.tools import MAIL_TOOLS, build_system_prompt


class MailAgent(AgentDef):
    name = "mail"
    tools = MAIL_TOOLS

    def system_prompt(self) -> str:
        return build_system_prompt(
            role=(
                "an email intent parser. You receive the user's command and the current "
                "email list. Return a plan of actions as JSON. Use indices (1-based) to "
                "reference specific emails. For deletes, use mail_move with folder='Trash'. "
                "For saves, use mail_move with folder='Saved'. For reading an email, use "
                "answer with the index. For fetching more, use mail_read. You do not "
                "generate display text."
            ),
            tools=self.tools,
            memory=load_memory("mail"),
        )
