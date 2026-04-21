"""Mail routes — /api/mail/*."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from gateway.middleware import get_session_id, get_user_id
from gateway.session import load_session, save_session
from services.mail.service import (
    EmailNotFoundError,
    ImapConnectionError,
    MailService,
    NoActiveSessionError,
)
from core.config import IMAP_ACCOUNTS


router = APIRouter()


class FetchRequest(BaseModel):
    account: str = ""
    count: int = 0
    unread_only: bool = False


class MoveRequest(BaseModel):
    indices: list[int]
    folder: str = "Trash"


def _require_session(request):
    from fastapi import Request

    session_id = get_session_id(request)
    user_id = get_user_id(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    return session_id, load_session(session_id, user_id)


@router.get("/api/mail")
def mail_get(request, page: int = 0):
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
def mail_fetch(request, body: FetchRequest):
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
def mail_move(request, body: MoveRequest):
    session_id, state = _require_session(request)
    service = MailService(state)
    message = service.move(body.indices, body.folder)
    state.mail_engine = service.to_dict()
    save_session(state)
    return {"message": message, "folder": body.folder}


@router.get("/api/mail/{index}")
def mail_read(request, index: int):
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