# Service Architecture Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Context:** Spec at `docs/superpowers/specs/2026-04-20-service-architecture-design.md`. Run tests after every step — server must stay up and tests must stay green throughout.

**Goal:** Split the monolith into independent logical services (`auth`, `mail`, `memory`, `search`) with a thin FastAPI gateway. Each service owns its tables, exposes typed error classes, and communicates via Protocol interfaces.

**Architecture:** Services are Python packages under `src/services/`. The FastAPI server lives in `src/gateway/`. `src/core/` retains only shared utilities (config, crypto, llm, docker). Services do NOT import each other — the gateway orchestrates.

**Tech Stack:** Python, FastAPI, SQLite, Ollama.

---

## Chunk 1: Foundation — Directory Structure, Interfaces, Session Store

**Goal:** Create the skeleton that all services hang on. No business logic here — just the directory structure, shared interfaces, error base classes, and session store in the gateway.

### Step 1: Create directory structure

```bash
mkdir -p src/services/auth src/services/mail/actions src/services/memory src/services/search
mkdir -p src/gateway/routes
mkdir -p tests/services tests/gateway
touch src/services/__init__.py
touch src/services/auth/__init__.py
touch src/services/mail/__init__.py
touch src/services/mail/actions/__init__.py
touch src/services/memory/__init__.py
touch src/services/search/__init__.py
touch src/gateway/__init__.py
touch src/gateway/routes/__init__.py
```

### Step 2: Create `src/services/interfaces.py`

**File:** Create: `src/services/interfaces.py`

```python
"""Service interface Protocols. Services use these to type-hint without importing."""
from typing import Protocol


class AuthServiceInterface(Protocol):
    def login(self, email: str, password: str) -> "AuthResult": ...
    def get_user(self, user_id: str) -> "User": ...
    def verify_password(self, user_id: str, password: str) -> bool: ...
    def register(self, email: str, password: str) -> "AuthResult": ...
    def add_imap_account(self, user_id: str, account: "ImapAccount", user_password: str) -> "ImapAccountResponse": ...
    def list_imap_accounts(self, user_id: str) -> list["ImapAccountResponse"]: ...
    def delete_imap_account(self, user_id: str, account_id: int) -> bool: ...
    def delete_user(self, user_id: str) -> bool: ...


class MailServiceInterface(Protocol):
    def fetch(self, count: int, unread_only: bool, account: str) -> "MailListResult": ...
    def move(self, indices: list[int], folder: str) -> str: ...
    def read(self, index: int) -> "EmailDetail": ...
    def handle(self, prompt: str, interactive: bool) -> list[dict]: ...
    def to_dict(self) -> dict: ...


class MemoryServiceInterface(Protocol):
    def remember(self, fact: str, user_id: str) -> str: ...
    def recall(self, query: str, user_id: str, top_k: int) -> list[dict]: ...
    def list_memories(self, user_id: str) -> list[dict]: ...
    def forget(self, memory_id: str, user_id: str) -> bool: ...


class SearchServiceInterface(Protocol):
    def search(self, query: str) -> dict: ...
    def browse(self, url: str) -> dict: ...
```

### Step 3: Create `src/services/errors.py`

**File:** Create: `src/services/errors.py`

```python
"""Base error class for all service exceptions."""


class ServiceError(Exception):
    """Base class for service errors. Caught by gateway and mapped to HTTP 502."""

    pass
```

### Step 4: Move `SessionStore` to `src/gateway/session.py`

**File:** Create: `src/gateway/session.py`

```python
"""Session state management — gateway-owned. Moved from src/core/session_store.py."""
import json
import time
import uuid
from dataclasses import dataclass

import sqlite3
from core.db import _connect


@dataclass
class SessionState:
    """Persistent session state — identity and mail inbox only."""
    session_id: str = ""
    user_id: str = ""
    mail_engine: dict | None = None
    imap_accounts: list[dict] | None = None
    pending: dict | None = None


class SessionStore:
    """Manages conversation sessions linked to users."""

    def create_session(self, user_id: str, imap_accounts: list[dict] | None = None) -> str:
        session_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, imap_accounts, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, json.dumps(imap_accounts) if imap_accounts else None, now, now),
        )
        conn.commit()
        conn.close()
        return session_id

    def get_session(self, session_id: str) -> SessionState | None:
        conn = _connect()
        row = conn.execute(
            "SELECT session_id, user_id, mail_engine, imap_accounts, pending FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return SessionState(
            session_id=row[0],
            user_id=row[1],
            mail_engine=json.loads(row[2]) if row[2] else None,
            imap_accounts=json.loads(row[3]) if row[3] else None,
            pending=json.loads(row[4]) if row[4] else None,
        )

    def save_session(self, state: SessionState) -> None:
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, user_id, mail_engine, imap_accounts, pending, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                state.session_id,
                state.user_id,
                json.dumps(state.mail_engine) if state.mail_engine else None,
                json.dumps(state.imap_accounts) if state.imap_accounts else None,
                json.dumps(state.pending) if state.pending else None,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def delete_session(self, session_id: str) -> None:
        conn = _connect()
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def get_sessions_for_user(self, user_id: str) -> list[SessionState]:
        conn = _connect()
        rows = conn.execute(
            "SELECT session_id, user_id, mail_engine, imap_accounts FROM sessions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()
        return [
            SessionState(
                session_id=r[0],
                user_id=r[1],
                mail_engine=json.loads(r[2]) if r[2] else None,
                imap_accounts=json.loads(r[3]) if r[3] else None,
            )
            for r in rows
        ]

    def count_sessions(self) -> int:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        return count

    def list_sessions(self) -> list[dict]:
        conn = _connect()
        rows = conn.execute(
            "SELECT session_id, user_id, mail_engine IS NOT NULL, created_at, updated_at FROM sessions"
        ).fetchall()
        conn.close()
        return [
            {
                "session_id": r[0],
                "user_id": r[1],
                "has_mail_engine": bool(r[2]),
                "created_at": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]


_session_store = SessionStore()


def load_session(session_id: str, user_id: str) -> SessionState:
    state = _session_store.get_session(session_id)
    if not state:
        from services.auth.errors import UserNotFoundError
        raise UserNotFoundError(f"Session {session_id} not found")
    if state.user_id != user_id:
        from services.auth.errors import InvalidCredentialsError
        raise InvalidCredentialsError("Session does not belong to this user")
    return state


def save_session(state: SessionState) -> None:
    _session_store.save_session(state)
```

> **Note:** `load_session` currently imports from `services.auth.errors`. This creates a temporary dependency. Once auth service is built (Chunk 2), it will be the proper import. For now, create a stub in `services/auth/errors.py` with just `UserNotFoundError` and `InvalidCredentialsError`.

### Step 5: Create stub `src/services/auth/errors.py`

**File:** Create: `src/services/auth/errors.py`

```python
"""Auth service errors."""
from services.errors import ServiceError


class AuthServiceError(ServiceError):
    pass


class UserExistsError(AuthServiceError):
    pass


class InvalidCredentialsError(AuthServiceError):
    pass


class UserNotFoundError(AuthServiceError):
    pass


class DecryptionError(AuthServiceError):
    pass
```

### Step 6: Create `src/gateway/middleware.py`

**File:** Create: `src/gateway/middleware.py`

```python
"""Gateway middleware — API key validation and session loading."""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from core.config import API_KEY


def require_api_key(request: Request, call_next):
    """Validate X-API-Key for admin endpoints."""
    if API_KEY and request.url.path.startswith("/api/admin"):
        if request.url.path == "/api/admin/login":
            return call_next(request)
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return call_next(request)


def get_session_id(request: Request) -> str | None:
    return request.headers.get("X-Session-ID") or request.query_params.get("session_id")


def get_user_id(request: Request) -> str | None:
    return request.headers.get("X-User-ID")
```

### Step 7: Update `src/core/session_store.py` to re-export from gateway

**File:** Modify: `src/core/session_store.py`

After the refactor, `src/core/session_store.py` simply re-exports from `gateway/session.py` to avoid breaking existing imports during the transition:

```python
"""Re-export SessionState and SessionStore from gateway for backward compatibility."""
from gateway.session import SessionState, SessionStore, load_session, save_session

__all__ = ["SessionState", "SessionStore", "load_session", "save_session"]
```

### Step 8: Run tests to verify nothing is broken

```bash
cd /home/alex/projects/MyAgent
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass. If any fail due to import issues, fix them before proceeding.

### Step 9: Commit

```bash
git add src/services/ src/gateway/ src/core/session_store.py
git commit -m "$(cat <<'EOF'
feat: create services/ and gateway/ directory structure

Add foundation for service architecture:
- services/interfaces.py with Protocol definitions
- services/errors.py base ServiceError class
- services/auth/errors.py stub (UserNotFoundError, InvalidCredentialsError, etc.)
- gateway/session.py (SessionStore + SessionState, moved from core)
- gateway/middleware.py (require_api_key, get_session_id, get_user_id)
- core/session_store.py now re-exports from gateway for compat

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Chunk 2: Auth Service

**Goal:** Build the auth service with full `AuthService`, owned `UserStore`, Pydantic models, and error classes. Wire it into `gateway/routes/auth.py`.

### Step 1: Create `src/services/auth/models.py`

**File:** Create: `src/services/auth/models.py`

```python
"""Pydantic models for auth service."""
from pydantic import BaseModel


class AuthResult(BaseModel):
    user_id: str
    session_id: str
    account: str


class User(BaseModel):
    user_id: str
    email: str
    created_at: float


class ImapAccount(BaseModel):
    name: str
    server: str
    port: int = 993
    username: str
    imap_password: str
    user_password: str  # used to derive the encryption key


class ImapAccountResponse(BaseModel):
    id: str
    name: str
    server: str
    username: str
    created_at: str
```

### Step 2: Create `src/services/auth/store.py`

**File:** Create: `src/services/auth/store.py`

(Moved from `src/core/db.py` — UserStore only.)

```python
"""User store — auth service owned. Moved from src/core/db.py."""
import json
import time
import uuid

import sqlite3
from core.db import _connect
from core.crypto import hash_password, verify_password


class UserStore:
    """Manages user identity and encrypted IMAP credentials."""

    def create_user(self, email: str, password: str) -> str:
        user_id = str(uuid.uuid4())
        now = time.time()
        pw_hash = json.dumps(hash_password(password))
        conn = _connect()
        conn.execute(
            "INSERT INTO users (user_id, email, password_hash, encrypted_imap_creds, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email.lower(), pw_hash, None, now, now),
        )
        conn.commit()
        conn.close()
        return user_id

    def verify_password(self, user_id: str, password: str) -> bool:
        user = self.get_user_by_id(user_id)
        if not user or not user["password_hash"]:
            return False
        stored = json.loads(user["password_hash"])
        return verify_password(password, stored)

    def get_user_by_email(self, email: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds FROM users WHERE email = ?",
            (email.lower(),),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "encrypted_imap_creds": row[3],
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "encrypted_imap_creds": row[3],
        }

    def update_imap_creds(self, user_id: str, encrypted_creds: list) -> None:
        now = time.time()
        blob = json.dumps(encrypted_creds).encode()
        conn = _connect()
        conn.execute(
            "UPDATE users SET encrypted_imap_creds = ?, updated_at = ? WHERE user_id = ?",
            (blob, now, user_id),
        )
        conn.commit()
        conn.close()

    def delete_user(self, user_id: str) -> None:
        conn = _connect()
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def list_users(self) -> list[dict]:
        conn = _connect()
        rows = conn.execute(
            "SELECT user_id, email, created_at, updated_at FROM users"
        ).fetchall()
        conn.close()
        return [
            {"user_id": r[0], "email": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def count_users(self) -> int:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return count
```

### Step 3: Create `src/services/auth/service.py`

**File:** Create: `src/services/auth/service.py`

```python
"""Auth service — owns user identity and IMAP credential management."""
import json

from core.crypto import decrypt_payload, encrypt_payload
from services.auth.errors import (
    AuthServiceError,
    UserExistsError,
    InvalidCredentialsError,
    DecryptionError,
    UserNotFoundError,
)
from services.auth.models import AuthResult, User, ImapAccount, ImapAccountResponse
from services.auth.store import UserStore
from gateway.session import SessionStore


class AuthService:
    """User registration, login, password verification, IMAP credential management."""

    def __init__(self):
        self._store = UserStore()
        self._session_store = SessionStore()

    def register(self, email: str, password: str) -> AuthResult:
        existing = self._store.get_user_by_email(email)
        if existing:
            raise UserExistsError(f"User {email} already exists")

        user_id = self._store.create_user(email, password)
        session_id = self._session_store.create_session(user_id)

        return AuthResult(
            user_id=user_id,
            session_id=session_id,
            account=email.split("@")[-1],
        )

    def login(self, email: str, password: str) -> AuthResult:
        user = self._store.get_user_by_email(email)
        if not user:
            raise InvalidCredentialsError("Invalid email or password")

        if not self._store.verify_password(user["user_id"], password):
            raise InvalidCredentialsError("Invalid email or password")

        # Decrypt stored IMAP credentials
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
                        plaintext = decrypt_payload(enc, password)
                        imap_accounts.append({
                            "name": acc.get("name", ""),
                            "host": plaintext.get("host", ""),
                            "port": plaintext.get("port", 993),
                            "user": plaintext.get("username", ""),
                            "password": plaintext.get("password", ""),
                        })
            except Exception:
                raise DecryptionError("Failed to decrypt IMAP credentials — wrong password?")

        session_id = self._session_store.create_session(user["user_id"], imap_accounts=imap_accounts or None)

        return AuthResult(
            user_id=user["user_id"],
            session_id=session_id,
            account=email.split("@")[-1],
        )

    def get_user(self, user_id: str) -> User:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return User(user_id=user["user_id"], email=user["email"], created_at=0)  # type: ignore[arg-type]

    def verify_password(self, user_id: str, password: str) -> bool:
        return self._store.verify_password(user_id, password)

    def add_imap_account(
        self, user_id: str, account: ImapAccount, user_password: str
    ) -> ImapAccountResponse:
        if not self._store.verify_password(user_id, user_password):
            raise InvalidCredentialsError("Invalid password")

        encrypted = encrypt_payload(
            {
                "host": account.server,
                "port": account.port,
                "username": account.username,
                "password": account.imap_password,
            },
            user_password,
        )

        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        blob = user["encrypted_imap_creds"]
        accounts = json.loads(blob.decode() if isinstance(blob, bytes) else (blob or "[]"))

        accounts.append({
            "name": account.name,
            "server": account.server,
            "username": account.username,
            "encrypted": encrypted,
        })

        self._store.update_imap_creds(user_id, accounts)

        return ImapAccountResponse(
            id=str(len(accounts) - 1),
            name=account.name,
            server=account.server,
            username=account.username,
            created_at="",
        )

    def list_imap_accounts(self, user_id: str) -> list[ImapAccountResponse]:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

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

    def delete_imap_account(self, user_id: str, account_id: int) -> bool:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        blob = user["encrypted_imap_creds"]
        accounts = json.loads(blob.decode() if isinstance(blob, bytes) else (blob or "[]"))

        if account_id < 0 or account_id >= len(accounts):
            raise UserNotFoundError(f"Account {account_id} not found")

        accounts.pop(account_id)
        self._store.update_imap_creds(user_id, accounts)
        return True

    def delete_user(self, user_id: str) -> bool:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        self._store.delete_user(user_id)
        return True
```

### Step 4: Create `src/gateway/routes/auth.py`

**File:** Create: `src/gateway/routes/auth.py`

(Mirrors the existing `/api/account/*` and `/api/admin/*` routes from `src/server/__main__.py`, but uses `AuthService`.)

```python
"""Auth routes — /api/account/* and /api/admin/*."""
from fastapi import APIRouter, Request, HTTPException

from pydantic import BaseModel
from services.auth.service import AuthService
from services.auth.errors import AuthServiceError
from services.auth.models import AuthResult, ImapAccount
from core.config import API_KEY


_auth_service = AuthService()

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class ImapAccountRequest(BaseModel):
    name: str
    server: str
    port: int = 993
    username: str
    imap_password: str
    user_password: str


class AccountInfo(BaseModel):
    email: str
    account: str


def _require_admin(request: Request) -> None:
    if not API_KEY:
        raise HTTPException(status_code=403, detail="Admin disabled — set MYDEVTEAM_API_KEY")
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Admin access requires valid API key")


@router.post("/api/account/register", response_model=AuthResult)
def register(req: RegisterRequest):
    try:
        return _auth_service.register(req.email, req.password)
    except AuthServiceError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/api/account/login", response_model=AuthResult)
def login(req: LoginRequest):
    try:
        return _auth_service.login(req.email, req.password)
    except AuthServiceError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/api/account/me", response_model=AccountInfo)
def me(request: Request):
    from gateway.middleware import get_user_id
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    try:
        user = _auth_service.get_user(user_id)
        return AccountInfo(email=user.email, account=user.email.split("@")[-1])
    except AuthServiceError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/api/account/logout")
def logout(request: Request):
    from gateway.middleware import get_session_id
    from gateway.session import _session_store
    session_id = get_session_id(request)
    if session_id:
        _session_store.delete_session(session_id)
    return {"ok": True}


@router.get("/api/imap")
def list_imap(request: Request):
    from gateway.middleware import get_user_id
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    try:
        return _auth_service.list_imap_accounts(user_id)
    except AuthServiceError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/api/imap")
def add_imap(request: Request, body: ImapAccountRequest):
    from gateway.middleware import get_user_id
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    try:
        account = ImapAccount(
            name=body.name,
            server=body.server,
            port=body.port,
            username=body.username,
            imap_password=body.imap_password,
            user_password=body.user_password,
        )
        return _auth_service.add_imap_account(user_id, account, body.user_password)
    except AuthServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/imap/{account_id}")
def delete_imap(request: Request, account_id: str):
    from gateway.middleware import get_user_id
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    try:
        _auth_service.delete_imap_account(user_id, int(account_id))
        return {"ok": True}
    except AuthServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


# Admin endpoints

class AdminLoginResponse(BaseModel):
    ok: bool
    message: str


@router.post("/api/admin/login", response_model=AdminLoginResponse)
def admin_login(req: AdminLoginRequest):
    if req.username != "admin":
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    if req.password != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return AdminLoginResponse(ok=True, message="Admin authenticated")


@router.get("/api/admin/stats")
def admin_stats(request: Request):
    _require_admin(request)
    import os
    from core.db import DB_PATH
    from gateway.session import _session_store
    db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    return {
        "users": _auth_service._store.count_users(),
        "sessions": _session_store.count_sessions(),
        "db_size_bytes": db_size,
    }


@router.get("/api/admin/users")
def admin_users(request: Request):
    _require_admin(request)
    return _auth_service._store.list_users()


@router.get("/api/admin/sessions")
def admin_sessions(request: Request):
    _require_admin(request)
    from gateway.session import _session_store
    return _session_store.list_sessions()


@router.delete("/api/admin/users/{user_id}")
def admin_delete_user(request: Request, user_id: str):
    _require_admin(request)
    try:
        _auth_service.delete_user(user_id)
        return {"ok": True}
    except AuthServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/api/admin/sessions/{session_id}")
def admin_delete_session(request: Request, session_id: str):
    _require_admin(request)
    from gateway.session import _session_store
    _session_store.delete_session(session_id)
    return {"ok": True}
```

### Step 5: Run tests

```bash
cd /home/alex/projects/MyAgent
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

All tests should pass. Import paths may need temporary `sys.path` hacks or the existing test files may need import updates if they import `UserStore` directly from `core.db`. Add a re-export in `core/db.py` if needed: `from services.auth.store import UserStore`.

### Step 6: Commit

```bash
git add src/services/auth/ src/gateway/routes/auth.py
git commit -m "$(cat <<'EOF'
feat: implement auth service

- services/auth/models.py: AuthResult, User, ImapAccount, ImapAccountResponse
- services/auth/store.py: UserStore (moved from core/db.py)
- services/auth/service.py: AuthService — register, login, IMAP account CRUD
- services/auth/errors.py: UserExistsError, InvalidCredentialsError, DecryptionError, UserNotFoundError
- gateway/routes/auth.py: /api/account/*, /api/admin/* routes using AuthService

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Chunk 3: Memory Service

**Goal:** Build memory service with fixed duplicate functions. Wire into `gateway/routes/memory.py`.

### Step 1: Create `src/services/memory/service.py`

**File:** Create: `src/services/memory/service.py`

Fixes the duplicate function bug from `src/core/memory.py` (original had `recall`, `list_memories`, `forget` defined twice).

```python
"""Memory service — per-user semantic facts with embeddings. Owns memories table."""
import json
import time
import uuid
import struct
from pathlib import Path

import sqlite3
from core.db import _connect


class MemoryService:
    """Per-user memory with embedding-based semantic search via nomic-embed-text."""

    _EMBED_MODEL = "nomic-embed-text"

    def _embed(self, text: str) -> list[float]:
        import ollama

        resp = ollama.embeddings(model=self._EMBED_MODEL, prompt=text)
        return resp["embedding"]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b + 1e-8)

    def remember(self, fact: str, user_id: str) -> str:
        """Store a memory with its embedding. Returns memory_id."""
        memory_id = str(uuid.uuid4())
        now = time.time()
        embedding = self._embed(fact)
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        conn = _connect()
        conn.execute(
            "INSERT INTO memories (memory_id, user_id, content, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, user_id, fact, blob, now),
        )
        conn.commit()
        conn.close()
        return memory_id

    def recall(self, query: str, user_id: str, top_k: int = 5) -> list[dict]:
        """Semantic search over user memories. Returns top-k matches with scores."""
        query_vec = self._embed(query)
        conn = _connect()
        rows = conn.execute(
            "SELECT memory_id, content, embedding, created_at FROM memories WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()

        scored = []
        for row in rows:
            memory_id, content, blob, created_at = row
            vec = struct.unpack(f"{len(blob) // 4}f", blob)
            score = self._cosine(query_vec, list(vec))
            scored.append((score, memory_id, content, created_at))

        scored.sort(reverse=True)
        return [
            {
                "memory_id": mid,
                "content": content,
                "score": round(score, 4),
                "created_at": created_at,
            }
            for score, mid, content, created_at in scored[:top_k]
        ]

    def list_memories(self, user_id: str) -> list[dict]:
        """List all memories for a user, newest first."""
        conn = _connect()
        rows = conn.execute(
            "SELECT memory_id, content, created_at FROM memories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        conn.close()
        return [
            {"memory_id": r[0], "content": r[1], "created_at": r[2]} for r in rows
        ]

    def forget(self, memory_id: str, user_id: str) -> bool:
        """Delete a specific memory. Returns True if deleted."""
        conn = _connect()
        cur = conn.execute(
            "DELETE FROM memories WHERE memory_id = ? AND user_id = ?",
            (memory_id, user_id),
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0


# Legacy flat-file note helpers (agent-scoped, no user_id) — kept for compat
MEMORY_DIR = Path(__file__).parent / "memory"


def _file(agent: str) -> Path:
    MEMORY_DIR.mkdir(exist_ok=True)
    return MEMORY_DIR / f"{agent}.json"


def _load_file(agent: str) -> list[str]:
    f = _file(agent)
    return json.loads(f.read_text()) if f.exists() else []


def load_memory(agent: str = "shared") -> list[str]:
    """Legacy: load memory for an agent (disk-based)."""
    shared = _load_file("shared")
    if agent == "shared":
        return shared
    return shared + _load_file(agent)


_agents_memory: dict[str, list[str]] = {}


def note(fact: str, agent: str = "shared") -> None:
    """Legacy: save a note to an agent's memory (disk file, no embeddings)."""
    if agent not in _agents_memory:
        _agents_memory[agent] = _load_file(agent)
    _agents_memory[agent].append(fact)
    _file(agent).write_text(json.dumps(_agents_memory[agent], indent=2))


# Module-level instance for gateway use
_service = MemoryService()


def remember(fact: str, user_id: str) -> str:
    return _service.remember(fact, user_id)


def recall(query: str, user_id: str, top_k: int = 5) -> list[dict]:
    return _service.recall(query, user_id, top_k=top_k)


def list_memories(user_id: str) -> list[dict]:
    return _service.list_memories(user_id)


def forget(memory_id: str, user_id: str) -> bool:
    return _service.forget(memory_id, user_id)
```

### Step 2: Create `src/gateway/routes/memory.py`

**File:** Create: `src/gateway/routes/memory.py`

```python
"""Memory routes — /api/memory/*."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from gateway.middleware import get_user_id
from services.memory.service import remember, recall, list_memories, forget


router = APIRouter()


class MemoryAddRequest(BaseModel):
    content: str


class MemoryResponse(BaseModel):
    memory_id: str
    content: str
    score: float | None = None
    created_at: float | None = None


@router.post("/api/memory", response_model=MemoryResponse)
def memory_add(request: Request, body: MemoryAddRequest):
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    memory_id = remember(body.content, user_id)
    return MemoryResponse(memory_id=memory_id, content=body.content)


@router.get("/api/memory", response_model=list[MemoryResponse])
def memory_list(request: Request, q: str = "", top_k: int = 5):
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    if q:
        results = recall(q, user_id, top_k=top_k)
        return [
            MemoryResponse(memory_id=r["memory_id"], content=r["content"], score=r["score"], created_at=r["created_at"])
            for r in results
        ]
    else:
        results = list_memories(user_id)
        return [
            MemoryResponse(memory_id=r["memory_id"], content=r["content"], score=None, created_at=r["created_at"])
            for r in results
        ]


@router.delete("/api/memory/{memory_id}")
def memory_delete(request: Request, memory_id: str):
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    deleted = forget(memory_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}
```

### Step 3: Update `src/core/memory.py` to re-export from memory service

**File:** Modify: `src/core/memory.py`

Replace content to re-export from service for backward compat:

```python
"""Backward-compat re-export of memory service functions."""
from services.memory.service import remember, recall, list_memories, forget, note, load_memory, _service

__all__ = ["remember", "recall", "list_memories", "forget", "note", "load_memory"]
```

### Step 4: Run tests

```bash
cd /home/alex/projects/MyAgent
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

### Step 5: Commit

```bash
git add src/services/memory/ src/gateway/routes/memory.py src/core/memory.py
git commit -m "$(cat <<'EOF'
feat: implement memory service

- services/memory/service.py: MemoryService with MemoryStore merged in,
  fixed duplicate recall/list_memories/forget bug from original memory.py
- gateway/routes/memory.py: /api/memory/* routes
- core/memory.py: re-exports from services/memory for backward compat

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Chunk 4: Search Service

**Goal:** Extract search providers and build `SearchService`. Wire into `gateway/routes/search.py`.

### Step 1: Create `src/services/search/providers.py`

**File:** Create: `src/services/search/providers.py`

(Extracted from `src/core/search.py` — provider classes only.)

```python
"""Search providers — DuckDuckGo, Searx, Google. Extracted from core/search.py."""
from dataclasses import dataclass
from typing import Literal

from core.config import SEARCH_PROVIDER, SEARCH_SEARX_URL, GOOGLE_API_KEY, GOOGLE_SEARCH_CX


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class _DuckDuckGoProvider:
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    )
                )
        return results


class _SearxProvider:
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        import requests

        url = SEARCH_SEARX_URL.rstrip("/") + "/search"
        params = {"q": query, "format": "json", "engines": "google"}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                )
            )
        return results


class _GoogleProvider:
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        import requests

        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_SEARCH_CX,
            "q": query,
            "num": min(max_results, 10),
        }
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("items", []):
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                )
            )
        return results


def get_provider():
    """Return the configured search provider instance."""
    provider = SEARCH_PROVIDER.lower()
    if provider == "duckduckgo":
        return _DuckDuckGoProvider()
    elif provider == "searx":
        return _SearxProvider()
    elif provider == "google":
        return _GoogleProvider()
    else:
        raise ValueError(f"Unknown SEARCH_PROVIDER={provider!r}")
```

### Step 2: Create `src/services/search/service.py`

**File:** Create: `src/services/search/service.py`

```python
"""Search service — web search and URL browsing. Owns no persistent data."""
import re
from html import unescape
from typing import Literal

from core.config import SEARCH_LLM_PROVIDER, SEARCH_LLM_MODEL, SEARCH_OPENAI_MODEL, SEARCH_ANTHROPIC_MODEL
from core.llm import default_adapter
from services.search.providers import get_provider, SearchResult


class SearchServiceError(Exception):
    pass


class ProviderTimeoutError(SearchServiceError):
    pass


class BrowseError(SearchServiceError):
    pass


def _llm_model() -> str:
    provider = SEARCH_LLM_PROVIDER.lower()
    if provider == "ollama":
        return SEARCH_LLM_MODEL
    elif provider == "openai":
        return SEARCH_OPENAI_MODEL
    elif provider == "anthropic":
        return SEARCH_ANTHROPIC_MODEL
    else:
        return "qwen3:8b"


def _generate_answer(query: str, results: list[SearchResult]) -> str:
    context = "\n".join(f"- {r.title}: {r.snippet}" for r in results[:5])
    messages = [
        {"role": "system", "content": "You are a helpful research assistant."},
        {
            "role": "user",
            "content": f"Based on these search results:\n{context}\n\nAnswer this question: {query}",
        },
    ]
    return default_adapter.complete(messages, schema={}, model=_llm_model())


class SearchService:
    """Web search with configurable provider and LLM answer generation."""

    def search(self, query: str) -> dict:
        """Search the web and return an answer + results list."""
        try:
            provider = get_provider()
            results = provider.search(query)
        except Exception as e:
            if "timeout" in str(e).lower():
                raise ProviderTimeoutError(f"Search provider timed out: {e}") from e
            raise SearchServiceError(f"Search provider error: {e}") from e

        if not results:
            return {"answer": "No results found.", "results": []}

        try:
            answer = _generate_answer(query, results)
        except Exception:
            answer = " ".join(r.snippet for r in results[:3])

        return {
            "answer": answer,
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in results
            ],
        }

    def browse(self, url: str) -> dict:
        """Fetch a URL and summarize its content via LLM."""
        import requests
        from readability import readability

        if not url.startswith(("http://", "https://")):
            raise BrowseError(f"Invalid URL: {url}")

        try:
            resp = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MyDevTeam/1.0)"},
            )
            resp.raise_for_status()
        except requests.Timeout:
            raise ProviderTimeoutError(f"Fetch timed out for {url}") from None
        except requests.RequestException as e:
            raise BrowseError(f"Fetch failed for {url}: {e}") from e

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            raise BrowseError(f"Non-HTML response ({content_type}) for {url}")

        try:
            doc = readability.Document(resp.text)
            text = doc.summary()
            text = re.sub(r"<[^>]+>", "", text)
            text = unescape(text)
            text = " ".join(text.split())
        except Exception:
            text = resp.text[:4000]

        text = text[:4000]
        title = doc.title() if hasattr(doc, "title") else url

        summary = _browse_summarize(text, url, title)

        return {"summary": summary, "url": url, "title": title}


def _browse_summarize(text: str, url: str, title: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that summarizes web pages concisely.",
        },
        {
            "role": "user",
            "content": f"Summarize this page (URL: {url}, Title: {title}):\n\n{text[:3000]}",
        },
    ]
    return default_adapter.complete(messages, schema={}, model=_llm_model())
```

### Step 3: Create `src/gateway/routes/search.py`

**File:** Create: `src/gateway/routes/search.py`

```python
"""Search routes — /api/search/*."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.search.service import SearchService, SearchServiceError, ProviderTimeoutError, BrowseError


router = APIRouter()
_search_service = SearchService()


class SearchRequest(BaseModel):
    query: str


class SearchResultResponse(BaseModel):
    title: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    answer: str
    results: list[SearchResultResponse]


class BrowseResponse(BaseModel):
    summary: str
    url: str
    title: str | None


@router.post("/api/search", response_model=SearchResponse)
def api_search(req: SearchRequest):
    try:
        result = _search_service.search(req.query)
    except ProviderTimeoutError:
        raise HTTPException(status_code=504, detail="Search provider timed out")
    except SearchServiceError as e:
        raise HTTPException(status_code=502, detail=f"Search provider error: {e}")
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

    return SearchResponse(
        answer=result["answer"],
        results=[
            SearchResultResponse(title=r["title"], url=r["url"], snippet=r["snippet"])
            for r in result["results"]
        ],
    )


@router.get("/api/search/browse", response_model=BrowseResponse)
def api_browse(url: str):
    try:
        result = _search_service.browse(url)
    except ProviderTimeoutError:
        raise HTTPException(status_code=504, detail="Fetch timed out")
    except BrowseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

    return BrowseResponse(
        summary=result["summary"],
        url=result["url"],
        title=result.get("title"),
    )
```

### Step 4: Update `src/core/search.py` to re-export from search service

**File:** Modify: `src/core/search.py`

Replace content to re-export from service:

```python
"""Backward-compat re-export of search service."""
from services.search.service import SearchService, ProviderTimeoutError

_service = SearchService()

search_web = _service.search
browse_url = _service.browse

__all__ = ["search_web", "browse_url", "ProviderTimeoutError"]
```

### Step 5: Run tests

```bash
cd /home/alex/projects/MyAgent
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

### Step 6: Commit

```bash
git add src/services/search/ src/gateway/routes/search.py src/core/search.py
git commit -m "$(cat <<'EOF'
feat: implement search service

- services/search/providers.py: DuckDuckGo, Searx, Google (extracted from core/search.py)
- services/search/service.py: SearchService — search() and browse() with typed errors
- gateway/routes/search.py: /api/search/* routes
- core/search.py: re-exports from services/search for backward compat

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Chunk 5: Mail Service + Gateway Server Assembly

This is the largest chunk. It is split into two sub-chunks:

### Chunk 5a: Mail Service — File Moves

**Goal:** Move `MailEngine`, actions, and related files to `services/mail/`. Create `MailService`.

#### Step 1: Move `src/core/mail_engine.py` → `src/services/mail/engine.py`

Copy `src/core/mail_engine.py` to `src/services/mail/engine.py`. Update imports inside the file:
- `from core.config` → `from core.config` (still valid)
- `from core.actions.action` → `from services.mail.actions.action`
- `from core.crypto` → `from core.crypto` (still valid)

#### Step 2: Move `src/core/actions/action.py` → `src/services/mail/actions/action.py`

Copy to new location. No import changes needed since it has no intra-project imports.

#### Step 3: Move `src/core/actions/mail.py` → `src/services/mail/actions/mail.py`

Update import: `from core.actions.action import ...` → `from services.mail.actions.action import ...`

#### Step 4: Move `src/core/actions/mail_imap.py` → `src/services/mail/actions/mail_imap.py`

Update import: `from core.actions.action import ...` → `from services.mail.actions.action import ...`

#### Step 5: Move `src/core/actions/mail_applescript.py` → `src/services/mail/actions/mail_applescript.py`

No import changes needed.

#### Step 6: Create `src/services/mail/actions/__init__.py`

```python
"""Mail actions — IMAP and AppleScript backends."""
from services.mail.actions.action import Action, ActionType, Plan
from services.mail.actions.mail import refresh_mail, read_emails

__all__ = ["Action", "ActionType", "Plan", "refresh_mail", "read_emails"]
```

#### Step 7: Create `src/services/mail/service.py`

**File:** Create: `src/services/mail/service.py`

```python
"""Mail service — IMAP fetch, email display, move/delete. Owns email_cache table."""
from dataclasses import dataclass
from typing import Any

from gateway.session import SessionState
from services.mail.engine import MailEngine
from services.mail.actions.action import Action, ActionType


class MailServiceError(Exception):
    pass


class NoActiveSessionError(MailServiceError):
    pass


class ImapConnectionError(MailServiceError):
    pass


class EmailNotFoundError(MailServiceError):
    pass


class FolderResolutionError(MailServiceError):
    pass


@dataclass
class MailListResult:
    emails: list[dict]
    page: int
    total_pages: int
    total_emails: int
    content: str


@dataclass
class EmailDetail:
    index: int
    from_: str
    subject: str
    date: str
    body: str
    account: str
    uid: Any
    recommendation: str


class MailService:
    """Thin wrapper over MailEngine with session state bridging."""

    def __init__(self, session: SessionState):
        self._session = session
        self._engine: MailEngine | None = (
            MailEngine.from_dict(session.mail_engine, imap_accounts=session.imap_accounts)
            if session.mail_engine
            else None
        )

    def _require_engine(self) -> MailEngine:
        if not self._engine:
            raise NoActiveSessionError("No active mail session — call fetch first")
        return self._engine

    def fetch(self, count: int = 0, unread_only: bool = False, account: str = "") -> MailListResult:
        from core.config import IMAP_ACCOUNTS

        if not self._engine:
            self._engine = MailEngine(model="", imap_accounts=self._session.imap_accounts)

        try:
            self._engine.fetch(count=count, unread_only=unread_only, account=account)
        except ValueError as e:
            raise ImapConnectionError(str(e))

        result = self._engine._mail_list_result()
        return MailListResult(**result)

    def move(self, indices: list[int], folder: str) -> str:
        engine = self._require_engine()
        action = Action(type=ActionType.mail_move, indices=indices, folder=folder)
        message = engine.execute(action)
        return message

    def read(self, index: int) -> EmailDetail:
        engine = self._require_engine()
        email = engine._email_for_index(index)
        if email is None:
            raise EmailNotFoundError(f"No email at index {index}")
        return EmailDetail(
            index=index,
            from_=email.get("from", ""),
            subject=email.get("subject", ""),
            date=email.get("date", ""),
            body=email.get("body", ""),
            account=email.get("account", ""),
            uid=email.get("uid"),
            recommendation=email.get("recommendation", ""),
        )

    def handle(self, prompt: str, interactive: bool = False) -> list[dict]:
        engine = self._require_engine()
        return engine.handle(prompt, interactive=interactive)

    def to_dict(self) -> dict | None:
        return self._engine.to_dict() if self._engine else None
```

### Chunk 5b: Gateway Routes + Server Assembly

#### Step 8: Create `src/gateway/routes/mail.py`

**File:** Create: `src/gateway/routes/mail.py`

```python
"""Mail routes — /api/mail/*."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from gateway.middleware import get_session_id, get_user_id
from gateway.session import load_session, save_session
from services.mail.service import (
    MailService,
    MailServiceError,
    NoActiveSessionError,
    ImapConnectionError,
    EmailNotFoundError,
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


def _require_session(request: Request):
    session_id = get_session_id(request)
    user_id = get_user_id(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    return session_id, load_session(session_id, user_id)


@router.get("/api/mail")
def mail_get(request: Request, page: int = 0):
    session_id, state = _require_session(request)
    if not state.mail_engine:
        raise HTTPException(status_code=404, detail="No active mail session")
    service = MailService(state)
    service._engine.page = page if hasattr(service._engine, "page") else 0
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
```

#### Step 9: Create `src/gateway/routes/chat.py`

**File:** Create: `src/gateway/routes/chat.py`

```python
"""Chat route — /api/chat. Dispatches to agents."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from gateway.middleware import get_session_id, get_user_id
from gateway.session import load_session, save_session
from core.executor import dispatch_session


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

    user_id = get_user_id(request)
    session_id = get_session_id(request) or body.session_id

    try:
        if session_id and session_id != "_stateless":
            state = load_session(session_id, user_id=user_id or "")
            results = dispatch_session(state, body.prompt, body.model, confirm=body.confirm)
            save_session(state)
        else:
            from gateway.session import SessionState
            state = SessionState(session_id="_stateless", user_id=user_id or "")
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
```

#### Step 10: Create `src/gateway/__main__.py`

**File:** Create: `src/gateway/__main__.py`

```python
"""Gateway server — FastAPI entry point. Orchestrates services."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import ALLOWED_ORIGINS
from gateway.routes import auth, memory, search, mail, chat


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(memory.router)
app.include_router(search.router)
app.include_router(mail.router)
app.include_router(chat.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

#### Step 11: Create `src/gateway/routes/__init__.py`

```python
"""Gateway route modules."""
from gateway.routes import auth, memory, search, mail, chat

__all__ = ["auth", "memory", "search", "mail", "chat"]
```

#### Step 12: Update `src/server/__main__.py` to re-export from gateway

**File:** Modify: `src/server/__main__.py`

Replace entire content with:

```python
"""Gateway server re-export for backward compatibility."""
from gateway.__main__ import app

__all__ = ["app"]
```

This way `uvicorn server:app` and `python -m server` both continue to work.

### Chunk 5c: Cleanup

#### Step 13: Remove old moved files from `src/core/`

```bash
# Remove files that have been moved to services/
rm src/core/mail_engine.py
rm src/core/memory.py
rm src/core/search.py
rm src/core/actions/action.py
rm src/core/actions/mail.py
rm src/core/actions/mail_imap.py
rm src/core/actions/mail_applescript.py
rm src/core/session_store.py
# Remove empty directories
rmdir src/core/actions 2>/dev/null || true
```

> **Warning:** Verify all imports resolve before committing this step. Run tests.

#### Step 14: Update `src/core/__init__.py` if needed

Check if `src/core/__init__.py` imports anything from removed files. Update accordingly.

#### Step 15: Run tests

```bash
cd /home/alex/projects/MyAgent
python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

Fix any broken imports. Common issues:
- `from core.actions.action` → `from services.mail.actions.action`
- `from core.mail_engine` → `from services.mail.engine`
- `from core.memory` → `from services.memory.service`
- `from core.search` → `from services.search.service`
- `from core.session_store` → `from gateway.session`

#### Step 16: Commit

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: complete mail service and gateway server assembly

- services/mail/engine.py: MailEngine (moved from core/mail_engine.py)
- services/mail/actions/: action.py, mail.py, mail_imap.py, mail_applescript.py (moved)
- services/mail/service.py: MailService with typed error classes
- gateway/routes/mail.py: /api/mail/* routes using MailService
- gateway/routes/chat.py: /api/chat using dispatch_session
- gateway/__main__.py: FastAPI app assembling all route modules
- src/server/__main__.py: re-exports from gateway for backward compat
- Removed: core/mail_engine.py, core/memory.py, core/search.py,
  core/actions/, core/session_store.py (moved to gateway/)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Chunk 6: Final Cleanup

### Step 1: Update `src/core/db.py`

Remove `UserStore`, `MemoryStore`, `SessionStore` from `core/db.py` since they're now in their respective services:

- `UserStore` → `services/auth/store.py`
- `MemoryStore` → `services/memory/service.py`
- `SessionStore` → `gateway/session.py`

Keep only the `_connect`, `_init_schema`, `_migrate` functions and the module-level `_schema_initialized` flag.

### Step 2: Update `src/core/__init__.py`

Remove re-exports of moved classes.

### Step 3: Update `CLAUDE.md` and `README.md`

Update project layout in both files to reflect new structure.

### Step 4: Update test imports

Update `tests/test_mail_engine.py`, `tests/test_crypto_db.py`, `tests/test_session_store.py` to import from new paths.

Create `tests/services/` and `tests/gateway/` directories with initial test files if desired.

### Step 5: Run full test suite

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

### Step 6: Commit

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: complete service architecture cleanup

- core/db.py: removed UserStore, MemoryStore (now in services/)
- core/__init__.py: removed re-exports
- Updated CLAUDE.md and README.md with new directory structure
- Updated test imports to use new service paths

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```
