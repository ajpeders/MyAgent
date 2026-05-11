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


@router.get("/api/mail/folders")
def mail_folders(request: Request, account: str = ""):
    """List available IMAP folders for the user's account."""
    session_id, state, payload = _require_session(request)
    try:
        from src.core.actions.mail import fetch_mailboxes
        folders = fetch_mailboxes(
            account_name=account,
            imap_accounts=state.imap_accounts,
        )
        return {"folders": folders or ["Inbox", "Archive", "Trash", "Spam", "Sent", "Drafts"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError:
        return {"folders": ["Inbox", "Archive", "Trash", "Spam", "Sent", "Drafts"]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list folders: {e}")


class CreateFolderRequest(BaseModel):
    name: str
    account: str = ""


@router.post("/api/mail/folders/create")
def mail_create_folder(request: Request, body: CreateFolderRequest):
    """Create a new IMAP folder."""
    session_id, state, payload = _require_session(request)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Folder name is required")
    try:
        from src.core.actions.mail_imap import create_folder
        success = create_folder(
            folder_name=body.name.strip(),
            account_name=body.account,
            imap_accounts=state.imap_accounts,
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create folder")
        return {"folder": body.name.strip(), "created": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create folder: {e}")


class FetchRequest(BaseModel):
    account: str = ""
    count: int = 0
    unread_only: bool = False
    preferences: str = ""
    folder: str = ""


class MoveRequest(BaseModel):
    indices: list[int]
    folder: str = "Trash"


class AnalyzeRequest(BaseModel):
    indices: list[int] = []
    preferences: str = ""


class FeedbackRequest(BaseModel):
    index: int
    verdict: str
    text: str = ""


def _require_session(request: Request):
    payload = jwt_required(request)
    user_id = payload["user_id"]
    session_id = get_session_id(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    return session_id, load_session(session_id, user_id), payload


@router.get("/api/mail")
def mail_get(request: Request, page: int = 0):
    session_id, state, payload = _require_session(request)
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    try:
        result = service.current_page(page=page)
    except NoActiveSessionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "emails": result.emails,
        "page": result.page,
        "total_pages": result.total_pages,
        "total_emails": result.total_emails,
        "content": result.content,
    }


@router.post("/api/mail/dev-seed")
def mail_dev_seed(request: Request):
    """Seed fake emails for UI development — no IMAP required. Raw emails only, no AI analysis."""
    from src.core.mail_engine import MailEngine

    session_id, state, payload = _require_session(request)
    fake_emails = [
        {
            "uid": i,
            "from": sender,
            "subject": subject,
            "date": f"2026-04-{26 - i:02d}",
            "body": body,
            "account": account,
            "mailbox": "Inbox",
            "read": i % 3 != 0,
            "recommendation": "",
            "summary": "",
            "recommended_todo": "",
            "message_id": f"<fake-{i}@dev>",
        }
        for i, (sender, subject, body, account) in enumerate([
            ("alice@example.com", "Q2 Planning Meeting", "Hi team, let's sync on Q2 goals this Thursday at 2pm. Please review the attached doc beforehand.", "work"),
            ("noreply@github.com", "PR #482 merged: Fix auth timeout", "Your pull request has been merged into main. CI passed all checks.", "work"),
            ("promo@store.com", "Flash Sale: 50% off everything!", "Don't miss our biggest sale of the year. Use code SAVE50 at checkout.", "personal"),
            ("bob@example.com", "Re: API design review", "I've left comments on the OpenAPI spec. Main concern is the pagination approach — can we discuss?", "work"),
            ("security@bank.com", "Your monthly statement is ready", "Your April statement is now available in your online banking portal.", "personal"),
            ("carol@example.com", "Lunch tomorrow?", "Hey! Want to grab lunch at the new Thai place tomorrow around noon?", "personal"),
            ("noreply@linear.app", "3 issues assigned to you", "You have 3 new issues in the INGEST project: INGEST-401, INGEST-402, INGEST-403.", "work"),
            ("newsletter@techdigest.io", "This Week in AI: April 21", "Top stories: New transformer architecture beats SOTA on reasoning benchmarks...", "personal"),
            ("dave@example.com", "Deployment checklist for v2.1", "Attached is the deployment checklist. Please review before Friday's release.", "work"),
            ("noreply@aws.com", "AWS billing alert: $127.43", "Your estimated charges for this billing period have exceeded your alert threshold.", "work"),
        ], start=1)
    ]
    engine = MailEngine(model="dev", imap_accounts=[])
    engine.inbox = fake_emails
    engine.account = "dev"
    state.mail_engine = engine.to_dict()
    save_session(state)
    result = engine._mail_list_result()
    return {
        "emails": result["emails"],
        "page": result["page"],
        "total_pages": result["total_pages"],
        "total_emails": result["total_emails"],
        "content": result["content"],
    }


@router.post("/api/mail/fetch-only")
def mail_fetch_only(request: Request, body: FetchRequest):
    """Fetch emails from IMAP without running LLM analysis."""
    session_id, state, payload = _require_session(request)
    if not state.imap_accounts and not IMAP_ACCOUNTS:
        raise HTTPException(status_code=400, detail="No IMAP accounts configured")
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    result = service.fetch(count=body.count or 10, unread_only=body.unread_only, account=body.account, analyze=False, preferences=body.preferences, folder=body.folder)
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
    session_id, state, payload = _require_session(request)
    if not state.imap_accounts and not IMAP_ACCOUNTS:
        raise HTTPException(status_code=400, detail="No IMAP accounts configured")
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    result = service.fetch(count=body.count or 10, unread_only=body.unread_only, account=body.account, preferences=body.preferences, folder=body.folder)
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
    session_id, state, payload = _require_session(request)
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    message = service.move(body.indices, body.folder)
    state.mail_engine = service.to_dict()
    save_session(state)
    return {"message": message, "folder": body.folder}


@router.post("/api/mail/analyze")
def mail_analyze(request: Request, body: AnalyzeRequest):
    session_id, state, payload = _require_session(request)
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    try:
        result = service.analyze(indices=body.indices or None, preferences=body.preferences)
    except NoActiveSessionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    state.mail_engine = service.to_dict()
    save_session(state)
    return {
        "emails": result.emails,
        "page": result.page,
        "total_pages": result.total_pages,
        "total_emails": result.total_emails,
        "content": result.content,
    }


@router.post("/api/mail/feedback")
def mail_feedback(request: Request, body: FeedbackRequest):
    session_id, state, payload = _require_session(request)
    if body.verdict not in {"good", "bad"}:
        raise HTTPException(status_code=400, detail="verdict must be 'good' or 'bad'")
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    service.record_feedback(body.index, body.verdict, body.text)
    state.mail_engine = service.to_dict()
    save_session(state)
    return {"status": "ok"}


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
    session_id, state, payload = _require_session(request)

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

    return {"emails": emails}


class SearchRequest(BaseModel):
    text: str = ""
    from_addr: str = ""
    subject: str = ""
    date_start: str = ""
    date_end: str = ""
    account: str = ""
    folder: str = ""


@router.post("/api/mail/search")
def mail_search(request: Request, body: SearchRequest):
    session_id, state, payload = _require_session(request)
    before = ""
    if body.date_end:
        before = str(date_type.fromisoformat(body.date_end) + timedelta(days=1))
    try:
        from src.core.actions.mail_imap import search_emails
        emails = search_emails(
            text=body.text,
            from_addr=body.from_addr,
            subject=body.subject,
            since=body.date_start,
            before=before,
            mailbox=body.folder or "INBOX",
            account_name=body.account,
            imap_accounts=state.imap_accounts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")
    return {"emails": emails}


@router.get("/api/mail/{index}/attachment/{attachment_index}")
def mail_download_attachment(request: Request, index: int, attachment_index: int):
    """Download an attachment by email index and attachment index."""
    session_id, state, payload = _require_session(request)
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    try:
        email_detail = service.read(index)
    except EmailNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    uid = email_detail.uid
    if uid is None:
        raise HTTPException(status_code=400, detail="Email has no UID")

    from src.core.actions.mail_imap import fetch_attachment
    from fastapi.responses import Response
    try:
        filename, content_type, data = fetch_attachment(
            uid=int(uid),
            attachment_index=attachment_index,
            mailbox="INBOX",
            account_name=email_detail.account,
            imap_accounts=state.imap_accounts,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IMAP error: {e}")

    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/mail/{index}")
def mail_read(request: Request, index: int):
    session_id, state, payload = _require_session(request)
    service = MailService(state, enc_key=payload.get("enc_key", ""))
    service.mark_read(index)
    email = service.read(index)
    state.mail_engine = service.to_dict()
    save_session(state)
    result = {
        "index": email.index,
        "from": email.from_,
        "subject": email.subject,
        "date": email.date,
        "body": email.body,
        "account": email.account,
        "uid": email.uid,
        "recommendation": email.recommendation,
        "summary": email.summary,
        "recommended_todo": email.recommended_todo,
        "attachments": [{"filename": a["filename"], "content_type": a["content_type"], "size": a["size"]} for a in (email.attachments or [])],
    }
    if email.body_html:
        result["body_html"] = email.body_html
    return result
