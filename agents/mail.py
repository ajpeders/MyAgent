from .base import AgentDef
from actions.mail import fetch_mailboxes
from memory import load_memory
from tools import MAIL_TOOLS, build_system_prompt


class MailAgent(AgentDef):
    name = "mail"
    tools = MAIL_TOOLS

    def system_prompt(self) -> str:
        return build_system_prompt(
            role="a mail assistant that plans and executes email tasks",
            tools=self.tools,
            memory=load_memory("mail"),
            context={"Available mailboxes": fetch_mailboxes()},
        )
