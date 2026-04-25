"""Auth routes — /api/account/* and /api/admin/*."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.gateway.middleware import jwt_required, admin_required, get_session_id
from src.gateway.session import SessionStore
from src.services.auth.errors import AuthServiceError, InvalidCredentialsError, UserNotFoundError, UserExistsError
from src.services.auth.models import AuthResult, ImapAccount, ImapAccountResponse, User, LoginRequest, RegisterRequest
from src.services.auth.service import AuthService

router = APIRouter()
_auth_service = AuthService()
_session_store = SessionStore()


# ── Account endpoints ─────────────────────────────────────────────────────────

@router.post("/api/account/register")
async def register(req: RegisterRequest) -> JSONResponse:
    try:
        result = _auth_service.register(req.email, req.password)
        return JSONResponse(content=result.model_dump())
    except UserExistsError as e:
        return JSONResponse(status_code=409, content={"detail": str(e)})
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.post("/api/account/login")
async def login(req: LoginRequest) -> JSONResponse:
    try:
        result = _auth_service.login(req.email, req.password)
        resp = JSONResponse(content={
            "user_id": result.user_id,
            "token": result.token,
            "account": result.account,
        })
        return resp
    except InvalidCredentialsError as e:
        return JSONResponse(status_code=401, content={"detail": str(e)})
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.get("/api/account/me")
async def me(request: Request):
    payload = jwt_required(request)
    try:
        user = _auth_service.get_user(payload["user_id"])
        return JSONResponse(content=user.model_dump())
    except UserNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@router.post("/api/account/logout")
async def logout(request: Request):
    # JWT is stateless — client discards token. Clear server-side session if present.
    session_id = get_session_id(request)
    if session_id:
        _session_store.delete_session(session_id)
    return JSONResponse(content={"status": "ok"})


# ── Config: IMAP account endpoints ──────────────────────────────────────────────

@router.get("/api/config/imap")
async def list_imap(request: Request):
    payload = jwt_required(request)
    try:
        accounts = _auth_service.list_imap_accounts(payload["user_id"])
        return JSONResponse(content=[a.model_dump() for a in accounts])
    except UserNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@router.post("/api/config/imap")
async def add_imap(request: Request, account: ImapAccount):
    payload = jwt_required(request)
    enc_key = payload.get("enc_key", "")
    if not enc_key:
        return JSONResponse(status_code=401, content={"detail": "No encryption key in token — re-login required"})
    try:
        result = _auth_service.add_imap_account(payload["user_id"], account, enc_key)
        return JSONResponse(content=result.model_dump(), status_code=201)
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.get("/api/config/imap/{account_id}")
async def get_imap(request: Request, account_id: int):
    payload = jwt_required(request)
    try:
        accounts = _auth_service.list_imap_accounts(payload["user_id"])
        for a in accounts:
            if int(a.id) == account_id:
                return JSONResponse(content=a.model_dump())
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    except UserNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@router.put("/api/config/imap/{account_id}")
async def update_imap(request: Request, account_id: int, account: ImapAccount):
    payload = jwt_required(request)
    enc_key = payload.get("enc_key", "")
    if not enc_key:
        return JSONResponse(status_code=401, content={"detail": "No encryption key in token — re-login required"})
    try:
        result = _auth_service.update_imap_account(payload["user_id"], account_id, account, enc_key)
        return JSONResponse(content=result.model_dump())
    except AuthServiceError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.delete("/api/config/imap/{account_id}")
async def delete_imap(request: Request, account_id: int):
    payload = jwt_required(request)
    success = _auth_service.delete_imap_account(payload["user_id"], account_id)
    if not success:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    return JSONResponse(content={"status": "ok"})


# ── Legacy IMAP endpoints (redirect to /api/config/imap) ───────────────────────

@router.get("/api/imap")
async def list_imap_legacy(request: Request):
    return await list_imap(request)


@router.post("/api/imap")
async def add_imap_legacy(request: Request, account: ImapAccount):
    return await add_imap(request, account)


@router.delete("/api/imap/{account_id}")
async def delete_imap_legacy(request: Request, account_id: int):
    return await delete_imap(request, account_id)


# ── Admin endpoints (JWT is_admin required) ──────────────────────────────────

@router.get("/api/admin/stats")
async def admin_stats(request: Request):
    admin_required(request)
    from src.services.auth.store import UserStore
    store = UserStore()
    return JSONResponse(content={
        "users_count": store.count_users(),
        "sessions_count": _session_store.count_sessions(),
        "db_size_bytes": _get_db_size(),
    })


@router.get("/api/admin/users")
async def admin_list_users(request: Request):
    admin_required(request)
    from src.services.auth.store import UserStore
    store = UserStore()
    return JSONResponse(content=store.list_users())


@router.get("/api/admin/sessions")
async def admin_list_sessions(request: Request):
    admin_required(request)
    return JSONResponse(content=_session_store.list_sessions())


@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(request: Request, user_id: str):
    admin_required(request)
    success = _auth_service.delete_user(user_id)
    if not success:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    return JSONResponse(content={"status": "deleted"})


@router.delete("/api/admin/sessions/{session_id}")
async def admin_delete_session(request: Request, session_id: str):
    admin_required(request)
    _session_store.delete_session(session_id)
    return JSONResponse(content={"status": "deleted"})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_db_size() -> int:
    from pathlib import Path
    db_path = Path(__file__).parent.parent.parent / "data.db"
    if db_path.exists():
        return db_path.stat().st_size
    return 0