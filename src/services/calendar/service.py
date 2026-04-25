"""Calendar service — per-user event management."""
from src.services.calendar.errors import EventNotFoundError
from src.services.calendar.models import CalendarEvent
from src.services.calendar.store import CalendarStore


class CalendarService:
    def __init__(self):
        self._store = CalendarStore()

    def create_event(
        self, user_id: str, title: str, date: str,
        time: str | None = None, description: str | None = None,
    ) -> CalendarEvent:
        row = self._store.create_event(user_id, title, date, time_=time, description=description)
        return CalendarEvent(**row)

    def get_events(self, user_id: str, start: str, end: str) -> list[CalendarEvent]:
        rows = self._store.get_events_in_range(user_id, start, end)
        return [CalendarEvent(**r) for r in rows]

    def delete_event(self, event_id: str, user_id: str) -> None:
        if not self._store.delete_event(event_id, user_id):
            raise EventNotFoundError(f"Event {event_id} not found")
