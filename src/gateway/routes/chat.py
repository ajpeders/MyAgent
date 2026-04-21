"""Chat route — /api/chat. Dispatches to agents."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from gateway.middleware import get_session_id, get_user_id
from gateway.session import load_session, save_session
from src.core.executor import dispatch_session
from src.core.session_store import SessionState


router = APIRouter()


class ChatRequest(BaseModel):
    prompt: str
    model: str = "qwen3:8b"
    session_id: str | None = None
    confirm: bool = False


class ActionResponse(BaseModel):
    type: str
    content: str
    agent: str | None = None
    pending_confirm: str | None = None
    emails: list[dict] | None = None
    page: int | None = None
    total_pages: int | None = None
    total_emails: int | None = None


@router.post("/api/chat")
async def chat(request: Request):
    try:
        body = ChatRequest.model_validate_json(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    user_id = get_user_id(request) or ""
    session_id = get_session_id(request) or body.session_id

    try:
        if session_id and session_id != "_stateless":
            state = load_session(session_id, user_id=user_id)
            results = dispatch_session(state, body.prompt, body.model, confirm=body.confirm)
            save_session(state)
        else:
            state = SessionState(session_id="_stateless", user_id=user_id)
            results = dispatch_session(state, body.prompt, body.model, confirm=body.confirm)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent backend failed: {exc}") from exc

    return [
        ActionResponse(
            type=r["type"],
            content=r["content"],
            agent=r.get("agent"),
            pending_confirm=r.get("pending_confirm"),
            emails=r.get("emails"),
            page=r.get("page"),
            total_pages=r.get("total_pages"),
            total_emails=r.get("total_emails"),
        )
        for r in results
    ]