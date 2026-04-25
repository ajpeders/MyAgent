"""Calendar service models."""
from pydantic import BaseModel


class CreateEventRequest(BaseModel):
    title: str
    date: str  # YYYY-MM-DD
    time: str | None = None  # HH:MM (24h)
    description: str | None = None


class CalendarEvent(BaseModel):
    id: str
    user_id: str
    title: str
    date: str
    time: str | None = None
    description: str | None = None
    created_at: float
