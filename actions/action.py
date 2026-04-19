from pydantic import BaseModel
from enum import Enum


class ActionType(str, Enum):
    misc        = "misc"
    answer      = "answer"
    summary     = "summary"
    warning     = "warning"
    command     = "command"
    mail_read   = "mail_read"
    mail_move   = "mail_move"
    mail_save   = "mail_save"
    ask_user    = "ask_user"
    note        = "note"
    remember    = "remember"
    web_search  = "web_search"
    personal_data = "personal_data"
    done        = "done"


class Action(BaseModel):
    type: ActionType
    content: str = ""
    count: int = 10
    unread_only: bool = False
    folder: str = "Archive"
    filter_from: str = ""
    filter_subject: str = ""
    continue_conversation: bool = False


class Plan(BaseModel):
    actions: list[Action] = []


class AgentRoute(BaseModel):
    agent: str   # "mail" | "command" | "answer"
    intent: str = ""  # brief summary of what the user wants

