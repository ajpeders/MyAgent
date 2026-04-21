"""Auth routes — /api/account/* and /api/admin/*."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core.config import API_KEY
from gateway.middleware import get_session_id, get_user_id
from gateway.session import SessionStore
from services.auth.errors import AuthServiceError, InvalidCredentialsError, UserNotFoundError, UserExistsError
from services.auth.models import AuthResult, ImapAccount, ImapAccountResponse, User
from services.auth.service import AuthService

router = APIRouter()
_auth_service = AuthService()
_session_store = SessionStore()


# ── Account endpoints ─────────────────────────────────────────────────────────

@router.post("/api/account/register")
async def register(email: str, password: str) -> JSONResponse:
    try:
        result = _auth_service.register(email, password)
        return JSONResponse(content=result.model_dump())
    except UserExistsError as e:
        return JSONResponse(status_code=409, content={"detail": str(e)})
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.post("/api/account/login")
async def login(email: str, password: str) -> JSONResponse:
    try:
        result = _auth_service.login(email, password)
        resp = JSONResponse(content=result.model_dump())
        resp.set_cookie(key="session_id", value=result.session_id, httponly=True)
        return resp
    except InvalidCredentialsError as e:
        return JSONResponse(status_code=401, content={"detail": str(e)})
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.get("/api/account/me")
async def me(request: Request):
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Missing X-User-ID"})
    try:
        user = _auth_service.get_user(user_id)
        return JSONResponse(content=user.model_dump())
    except UserNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@router.post("/api/account/logout")
async def logout(request: Request):
    session_id = get_session_id(request)
    if session_id:
        _session_store.delete_session(session_id)
    return JSONResponse(content={"status": "ok"})


# ── IMAP account endpoints ─────────────────────────────────────────────────────

@router.get("/api/imap")
async def list_imap(request: Request):
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Missing X-User-ID"})
    try:
        accounts = _auth_service.list_imap_accounts(user_id)
        return JSONResponse(content=[a.model_dump() for a in accounts])
    except UserNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@router.post("/api/imap")
async def add_imap(request: Request, account: ImapAccount, user_password: str):
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Missing X-User-ID"})
    try:
        result = _auth_service.add_imap_account(user_id, account, user_password)
        return JSONResponse(content=result.model_dump(), status_code=201)
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.delete("/api/imap/{account_id}")
async def delete_imap(request: Request, account_id: int):
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Missing X-User-ID"})
    success = _auth_service.delete_imap_account(user_id, account_id)
    if not success:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    return JSONResponse(content={"status": "ok"})


# ── Admin endpoints ─────────────────────────────────────────────────────────────

@router.post("/api/admin/login")
async def admin_login(username: str, password: str) -> JSONResponse:
    if username == "admin" and password == API_KEY:
        return JSONResponse(content={"status": "authenticated"})
    return JSONResponse(status_code=401, content={"detail": "Invalid admin credentials"})


@router.get("/api/admin/stats")
async def admin_stats():
    from services.auth.store import UserStore
    store = UserStore()
    return JSONResponse(content={
        "users_count": store.count_users(),
        "sessions_count": _session_store.count_sessions(),
        "db_size_bytes": _get_db_size(),
    })


@router.get("/api/admin/users")
async def admin_list_users():
    from services.auth.store import UserStore
    store = UserStore()
    return JSONResponse(content=store.list_users())


@router.get("/api/admin/sessions")
async def admin_list_sessions():
    return JSONResponse(content=_session_store.list_sessions())


@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str):
    success = _auth_service.delete_user(user_id)
    if not success:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    return JSONResponse(content={"status": "deleted"})


@router.delete("/api/admin/sessions/{session_id}")
async def admin_delete_session(session_id: str):
    _session_store.delete_session(session_id)
    return JSONResponse(content={"status": "deleted"})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_db_size() -> int:
    from pathlib import Path
    db_path = Path(__file__).parent.parent.parent / "data.db"
    if db_path.exists():
        return db_path.stat().st_size
    return 0