from pydantic import BaseModel, Field
from enum import Enum


class ActionType(str, Enum):
    misc        = "misc"
    answer      = "answer"
    summary     = "summary"
    warning     = "warning"
    command     = "command"
    mail_read   = "mail_read"
    mail_read_all = "mail_read_all"
    mail_create_folder = "mail_create_folder"
    mail_move   = "mail_move"
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
    folder: str = "Trash"
    folder_name: str = ""
    mailbox: str = "INBOX"
    filter_from: str = ""
    filter_subject: str = ""
    account: str = ""
    indices: list[int] = Field(default_factory=list)
    continue_conversation: bool = False


class Plan(BaseModel):
    actions: list[Action] = Field(default_factory=list)


class AgentRoute(BaseModel):
    agent: str   # "mail" | "command" | "core" | "answer"
    intent: str = ""  # brief summary of what the user wants
