"""Profile service models."""
from pydantic import BaseModel


class Signal(BaseModel):
    signal_id: str
    signal_type: str
    topic: str
    source: str
    created_at: float


class ContextSnapshot(BaseModel):
    user_id: str
    interests: list[str]
    recent_signals: list[Signal]
    calendar_today: list[dict]
    calendar_upcoming: list[dict]
    mail_subjects: list[str]
    memories: list[str]


class UpdateInterestsRequest(BaseModel):
    interests: list[str]


class UpdateModelConfigRequest(BaseModel):
    config: dict[str, str]


class LogSignalRequest(BaseModel):
    signal_type: str
    topic: str
    source: str = ""
