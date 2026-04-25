"""Calendar routes — /api/calendar/*."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.gateway.middleware import jwt_required
from src.services.calendar.errors import EventNotFoundError
from src.services.calendar.models import CreateEventRequest
from src.services.calendar.service import CalendarService

router = APIRouter()
_calendar = CalendarService()


@router.get("/api/calendar/events")
async def list_events(request: Request, start: str, end: str):
    payload = jwt_required(request)
    events = _calendar.get_events(payload["user_id"], start, end)
    return {"events": [e.model_dump() for e in events]}


@router.post("/api/calendar/events", status_code=201)
async def create_event(request: Request, body: CreateEventRequest):
    payload = jwt_required(request)
    event = _calendar.create_event(
        user_id=payload["user_id"],
        title=body.title,
        date=body.date,
        time=body.time,
        description=body.description,
    )
    return event.model_dump()


@router.delete("/api/calendar/events/{event_id}")
async def delete_event(request: Request, event_id: str):
    payload = jwt_required(request)
    try:
        _calendar.delete_event(event_id, payload["user_id"])
        return {"status": "deleted"}
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
