"""Mail routes — /api/mail/*."""
from datetime import date as date_type, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.gateway.middleware import get_session_id, jwt_required
from src.gateway.session import load_session, save_session
from src.services.mail.service import (
    EmailNotFoundError,
    ImapConnectionError,
    MailService,
    NoActiveSessionError,
)
from src.core.config import IMAP_ACCOUNTS


router = APIRouter()


class FetchRequest(BaseModel):
    account: str = ""
    count: int = 0
    unread_only: bool = False


class MoveRequest(BaseModel):
    indices: list[int]
    folder: str = "Trash"


def _require_session(request: Request):
    payload = jwt_required(request)
    user_id = payload["user_id"]
    session_id = get_session_id(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    return session_id, load_session(session_id, user_id)


@router.get("/api/mail")
def mail_get(request: Request, page: int = 0):
    session_id, state = _require_session(request)
    if not state.mail_engine:
        raise HTTPException(status_code=404, detail="No active mail session")
    service = MailService(state)
    if hasattr(service._engine, "page"):
        service._engine.page = page
    result = service.fetch()
    state.mail_engine = service.to_dict()
    save_session(state)
    return {
        "emails": result.emails,
        "page": result.page,
        "total_pages": result.total_pages,
        "total_emails": result.total_emails,
        "content": result.content,
    }


@router.post("/api/mail/fetch")
def mail_fetch(request: Request, body: FetchRequest):
    session_id, state = _require_session(request)
    if not state.imap_accounts and not IMAP_ACCOUNTS:
        raise HTTPException(status_code=400, detail="No IMAP accounts configured")
    service = MailService(state)
    result = service.fetch(count=body.count, unread_only=body.unread_only, account=body.account)
    state.mail_engine = service.to_dict()
    save_session(state)
    return {
        "emails": result.emails,
        "page": result.page,
        "total_pages": result.total_pages,
        "total_emails": result.total_emails,
        "content": result.content,
    }


@router.post("/api/mail/move")
def mail_move(request: Request, body: MoveRequest):
    session_id, state = _require_session(request)
    service = MailService(state)
    message = service.move(body.indices, body.folder)
    state.mail_engine = service.to_dict()
    save_session(state)
    return {"message": message, "folder": body.folder}


@router.get("/api/mail/by-date")
def mail_by_date(
    request: Request,
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account: str = "",
):
    """Fetch emails by date or date range.

    Single date:  ?date=2026-04-25
    Date range:   ?start=2026-04-01&end=2026-04-30
    """
    session_id, state = _require_session(request)

    if date:
        since = date
        # IMAP BEFORE is exclusive, so add 1 day
        before = str(date_type.fromisoformat(date) + timedelta(days=1))
    elif start and end:
        since = start
        before = str(date_type.fromisoformat(end) + timedelta(days=1))
    else:
        raise HTTPException(status_code=400, detail="Provide ?date= or ?start= and ?end=")

    try:
        from src.core.actions.mail_imap import fetch_by_date
        emails = fetch_by_date(
            since=since,
            before=before,
            account_name=account,
            imap_accounts=state.imap_accounts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IMAP error: {e}")

    return {"messages": emails}


@router.get("/api/mail/{index}")
def mail_read(request: Request, index: int):
    session_id, state = _require_session(request)
    service = MailService(state)
    email = service.read(index)
    return {
        "index": email.index,
        "from": email.from_,
        "subject": email.subject,
        "date": email.date,
        "body": email.body,
        "account": email.account,
        "uid": email.uid,
        "recommendation": email.recommendation,
    }