"""FastAPI server for MyDevTeam.

All user data (identity, IMAP credentials, email cache) is stored in SQLite
via core.db. Credentials and email cache are encrypted at rest.
"""
import json
import uuid

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import DEFAULT_MODEL, API_KEY, ALLOWED_ORIGINS
from core.crypto import decrypt_payload, encrypt_payload
from core.db import UserStore, EmailCacheStore, SessionStore
from core.executor import dispatch_session
from core.mail_engine import MailEngine
from core.session_store import SessionState, load_session, save_session

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/api"):
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
    return await call_next(request)


# --- Helpers ---------------------------------------------------------------

def _get_session_id(request: Request) -> str | None:
    """Extract session_id from X-Session-ID header or session_id query param."""
    return request.headers.get("X-Session-ID") or request.query_params.get("session_id")


def _get_user_id(request: Request) -> str | None:
    """Extract user_id from X-User-ID header."""
    return request.headers.get("X-User-ID")


# --- API models -----------------------------------------------------------

class ChatRequest(BaseModel):
    prompt: str
    model: str = DEFAULT_MODEL
    session_id: str | None = None


class ActionResponse(BaseModel):
    type: str
    content: str
    agent: str | None = None
    pending_confirm: str | None = None
    emails: list[dict] | None = None
    page: int | None = None
    total_pages: int | None = None
    total_emails: int | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    user_id: str
    session_id: str
    account: str


class ImapAccountRequest(BaseModel):
    name: str
    server: str
    port: int = 993
    username: str
    imap_password: str
    user_password: str  # User's login password — used to derive the encryption key


class ImapAccountResponse(BaseModel):
    id: str
    name: str
    server: str
    username: str
    created_at: str


class AccountInfo(BaseModel):
    email: str
    account: str


class FetchRequest(BaseModel):
    account: str = ""
    count: int = 0          # 0 = use server default
    unread_only: bool = False


class MoveRequest(BaseModel):
    indices: list[int]
    folder: str = "Trash"


class MailPageResponse(BaseModel):
    emails: list[dict]
    page: int
    total_pages: int
    total_emails: int
    content: str            # formatted display text for clients that want plain text


# --- Stores ---------------------------------------------------------------

_user_store = UserStore()
_email_cache = EmailCacheStore()
_session_store = SessionStore()


# --- API routes -----------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/account/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    """Register a new user. Creates a user row and an initial session.

    The user's password is hashed and stored for login verification.
    IMAP account details are added separately via POST /api/imap.
    """
    existing = _user_store.get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user_id = _user_store.create_user(req.email.lower(), req.password)
    session_id = _session_store.create_session(user_id)

    return AuthResponse(
        user_id=user_id,
        session_id=session_id,
        account=req.email.split("@")[-1],
    )


@app.post("/api/account/login", response_model=AuthResponse)
def login(req: LoginRequest):
    """Login with email + password.

    Verifies the password hash, decrypts IMAP credentials using the provided
    password, and creates a new session with the plaintext IMAP accounts so
    that IMAP operations can proceed without re-asking for the password.
    """
    user = _user_store.get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _user_store.verify_password(user["user_id"], req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Decrypt stored IMAP credentials using the provided password
    imap_accounts: list[dict] = []
    blob = user["encrypted_imap_creds"]
    if blob:
        try:
            if isinstance(blob, bytes):
                blob = blob.decode()
            stored = json.loads(blob)
            for acc in stored:
                enc = acc.get("encrypted", {})
                if enc:
                    plaintext = decrypt_payload(enc, req.password)
                    imap_accounts.append({
                        "name": acc.get("name", ""),
                        "host": plaintext.get("host", ""),
                        "port": plaintext.get("port", 993),
                        "user": plaintext.get("username", ""),
                        "password": plaintext.get("password", ""),
                    })
        except Exception:
            raise HTTPException(status_code=401, detail="Failed to decrypt IMAP credentials — wrong password?")

    session_id = _session_store.create_session(user["user_id"], imap_accounts=imap_accounts or None)

    return AuthResponse(
        user_id=user["user_id"],
        session_id=session_id,
        account=req.email.split("@")[-1],
    )


@app.get("/api/account/me", response_model=AccountInfo)
def me(request: Request):
    """Get current user info."""
    user_id = _get_user_id(request)
    session_id = _get_session_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    user = _user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return AccountInfo(email=user["email"], account=user["email"].split("@")[-1])


@app.post("/api/account/logout")
def logout(request: Request):
    """Logout and delete the current session."""
    session_id = _get_session_id(request)
    if session_id:
        _session_store.delete_session(session_id)
    return {"ok": True}


@app.get("/api/imap", response_model=list[ImapAccountResponse])
def list_imap(request: Request):
    """List user's IMAP accounts (metadata only — no passwords)."""
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")

    user = _user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    blob = user["encrypted_imap_creds"]
    if not blob:
        return []
    if isinstance(blob, bytes):
        blob = blob.decode()
    accounts = json.loads(blob)
    return [
        ImapAccountResponse(
            id=str(i),
            name=acc.get("name", ""),
            server=acc.get("server", ""),
            username=acc.get("username", ""),
            created_at="",
        )
        for i, acc in enumerate(accounts)
    ]


@app.post("/api/imap", response_model=ImapAccountResponse)
def add_imap(request: Request, body: ImapAccountRequest):
    """Add an IMAP account for the user.

    Credentials are encrypted at rest using a key derived from the user's
    login password (user_password). The plaintext password is never stored.
    """
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")

    user = _user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not _user_store.verify_password(user_id, body.user_password):
        raise HTTPException(status_code=401, detail="Invalid password")

    encrypted = encrypt_payload(
        {
            "host": body.server,
            "port": body.port,
            "username": body.username,
            "password": body.imap_password,
        },
        body.user_password,
    )

    blob = user["encrypted_imap_creds"]
    accounts = json.loads(blob.decode() if isinstance(blob, bytes) else (blob or "[]"))

    accounts.append({
        "name": body.name,
        "server": body.server,
        "username": body.username,
        "encrypted": encrypted,
    })

    _user_store.update_imap_creds(user_id, accounts)

    return ImapAccountResponse(
        id=str(len(accounts) - 1),
        name=body.name,
        server=body.server,
        username=body.username,
        created_at="",
    )


@app.delete("/api/imap/{account_id}")
def delete_imap(request: Request, account_id: str):
    """Remove an IMAP account."""
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")

    user = _user_store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    blob = user["encrypted_imap_creds"]
    accounts = json.loads(blob.decode() if isinstance(blob, bytes) else (blob or "[]"))

    idx = int(account_id)
    if idx < 0 or idx >= len(accounts):
        raise HTTPException(status_code=404, detail="Account not found")

    accounts.pop(idx)
    _user_store.update_imap_creds(user_id, accounts)
    return {"ok": True}


# --- Mail helpers -------------------------------------------------------------

def _require_session(request: Request) -> tuple[str, "SessionState"]:
    """Load session or raise 401/400. Returns (session_id, state)."""
    session_id = _get_session_id(request)
    user_id = _get_user_id(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    return session_id, load_session(session_id, user_id=user_id)


def _engine_from_session(state: "SessionState") -> "MailEngine":
    """Restore MailEngine from session or raise 404."""
    if not state.mail_engine:
        raise HTTPException(status_code=404, detail="No active mail session — call POST /api/mail/fetch first")
    return MailEngine.from_dict(state.mail_engine, imap_accounts=state.imap_accounts)


def _mail_page_response(engine: "MailEngine") -> MailPageResponse:
    result = engine._mail_list_result()
    return MailPageResponse(
        emails=result["emails"],
        page=result["page"],
        total_pages=result["total_pages"],
        total_emails=result["total_emails"],
        content=result["content"],
    )


# --- Mail endpoints -----------------------------------------------------------

@app.get("/api/mail", response_model=MailPageResponse)
def mail_get(request: Request, page: int = 0):
    """Return the current inbox page from the session mail engine."""
    session_id, state = _require_session(request)
    engine = _engine_from_session(state)
    engine.page = page
    return _mail_page_response(engine)


@app.post("/api/mail/fetch", response_model=MailPageResponse)
def mail_fetch(request: Request, body: FetchRequest):
    """Fetch (or re-fetch) inbox from IMAP and store in session."""
    session_id, state = _require_session(request)
    engine = (
        MailEngine.from_dict(state.mail_engine, imap_accounts=state.imap_accounts)
        if state.mail_engine
        else MailEngine(model="", imap_accounts=state.imap_accounts)
    )
    engine.fetch(count=body.count, unread_only=body.unread_only, account=body.account)
    state.mail_engine = engine.to_dict()
    save_session(state)
    return _mail_page_response(engine)


@app.post("/api/mail/move")
def mail_move(request: Request, body: MoveRequest):
    """Move emails by page-relative indices to a folder (default: Trash)."""
    from core.actions.action import Action, ActionType
    session_id, state = _require_session(request)
    engine = _engine_from_session(state)
    action = Action(type=ActionType.mail_move, indices=body.indices, folder=body.folder)
    message = engine.execute(action)
    state.mail_engine = engine.to_dict()
    save_session(state)
    return {"message": message, "folder": body.folder}


@app.post("/api/chat", response_model=list[ActionResponse])
async def chat(request: Request):
    try:
        body = ChatRequest.model_validate_json(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    user_id = _get_user_id(request)
    session_id = _get_session_id(request) or body.session_id

    try:
        if session_id and session_id != "_stateless":
            state = load_session(session_id, user_id=user_id or "")
            results = dispatch_session(state, body.prompt, body.model)
            save_session(state)
        else:
            state = SessionState(session_id="_stateless", user_id=user_id or "")
            results = dispatch_session(state, body.prompt, body.model)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent backend failed: {exc}",
        ) from exc

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
