# Service Architecture Design

> **Goal:** Split the monolith into independent logical services with clear boundaries, owned data stores, and typed interfaces — without introducing network overhead.

**Architecture:** Organise code into service packages (`auth`, `mail`, `memory`, `search`) with a thin FastAPI gateway. Services communicate through interface classes (Protocol), not direct imports. Each service owns its tables and exposes typed error classes that the gateway maps to HTTP.

**Tech Stack:** Python + FastAPI, SQLite (shared DB, service-owned tables), Ollama for embeddings and LLM.

---

## Services

### Auth Service — `services/auth/`

**Responsibility:** User registration, login, password verification, IMAP credential encryption/decryption.

**Owns:** `users` table.

**Public Interface:**
```python
class AuthService:
    def register(self, email: str, password: str) -> AuthResult
    def login(self, email: str, password: str) -> AuthResult
    def get_user(self, user_id: str) -> User
    def verify_password(self, user_id: str, password: str) -> bool
    def add_imap_account(self, user_id: str, account: ImapAccount, user_password: str) -> ImapAccountResponse
    def list_imap_accounts(self, user_id: str) -> list[ImapAccountResponse]
    def delete_imap_account(self, user_id: str, account_id: int) -> bool
    def delete_user(self, user_id: str) -> bool
```

**Error Types:** `UserExistsError`, `InvalidCredentialsError`, `DecryptionError`, `UserNotFoundError`.

**Data Model:**
```python
# services/auth/models.py
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
    user_password: str  # used to derive encryption key
```

---

### Mail Service — `services/mail/`

**Responsibility:** IMAP connection, inbox fetch, email display, move/delete to folders.

**Owns:** `email_cache` table, session-scoped `mail_engine` state (serialized dict).

**Public Interface:**
```python
class MailService:
    def __init__(self, session: SessionState): ...
    def fetch(self, count: int = 0, unread_only: bool = False, account: str = "") -> MailListResult
    def move(self, indices: list[int], folder: str) -> str  # returns message
    def read(self, index: int) -> EmailDetail
    def handle(self, prompt: str, interactive: bool = False) -> list[ActionResult]
    def to_dict(self) -> dict  # serialise engine state for session storage
    @classmethod
    def from_dict(cls, data: dict, imap_accounts: list[dict]) -> MailService
```

**Error Types:** `NoActiveSessionError`, `ImapConnectionError`, `EmailNotFoundError`, `FolderResolutionError`.

**Moved Files:**
- `src/core/mail_engine.py` → `services/mail/engine.py`
- `src/core/actions/mail.py` → `services/mail/actions/mail.py`
- `src/core/actions/mail_imap.py` → `services/mail/actions/mail_imap.py`
- `src/core/actions/mail_applescript.py` → `services/mail/actions/mail_applescript.py`
- `src/core/actions/action.py` → `services/mail/actions/action.py` (shared with other agents)

---

### Memory Service — `services/memory/`

**Responsibility:** Per-user semantic facts with embeddings. Stores memories in SQLite, generates embeddings via `nomic-embed-text` through Ollama.

**Owns:** `memories` table.

**Public Interface:**
```python
class MemoryService:
    def remember(self, fact: str, user_id: str) -> str  # returns memory_id
    def recall(self, query: str, user_id: str, top_k: int = 5) -> list[MemoryMatch]
    def list_memories(self, user_id: str) -> list[MemoryEntry]
    def forget(self, memory_id: str, user_id: str) -> bool
```

**Error Types:** `EmbeddingError`, `MemoryNotFoundError`.

**Bug Fixed:** Original `src/core/memory.py` had duplicate `recall`, `list_memories`, and `forget` definitions (lines 56–83 repeated lines 41–68). The service rewrite consolidates to single implementations.

---

### Search Service — `services/search/`

**Responsibility:** Web search via configurable provider (DuckDuckGo, Searx, Google), URL fetching and LLM summarization.

**Owns:** No persistent data (stateless).

**Public Interface:**
```python
class SearchService:
    def search(self, query: str) -> SearchResult
    def browse(self, url: str) -> BrowseResult
```

**Error Types:** `SearchProviderError`, `BrowseError`, `ProviderTimeoutError`.

**Configuration:** Same `SEARCH_PROVIDER`, `SEARCH_SEARX_URL`, `GOOGLE_API_KEY`, `SEARCH_LLM_*` config keys — moved to `services/search/config.py` (re-exports from `core.config`).

---

### API Gateway — `gateway/`

**Responsibility:** FastAPI routes, middleware, session management, agent dispatch. Orchestrates services but contains no business logic.

**Owns:** `sessions` table via `SessionStore`.

**Route Structure:**
```
gateway/routes/auth.py      — /api/account/*, /api/admin/*
gateway/routes/mail.py      — /api/mail/*
gateway/routes/memory.py    — /api/memory/*
gateway/routes/search.py    — /api/search/*
gateway/routes/chat.py      — /api/chat
```

**Middleware:**
- `require_api_key` — validates `X-API-Key` for admin endpoints
- `load_session` — extracts `X-Session-ID` / `X-User-ID`, loads `SessionState`

**Session Bridging:** The gateway creates `MailService(session)` with the loaded session state. Mail service never accesses the session store directly.

---

## Directory Structure

```
src/
  services/
    auth/
      __init__.py
      service.py     # AuthService + errors
      models.py      # Pydantic models
      store.py       # UserStore (from core/db.py, moved)
    mail/
      __init__.py
      service.py     # MailService — thin wrapper over engine
      engine.py      # MailEngine (moved from core/mail_engine.py)
      actions/       # IMAP actions (moved from core/actions/)
        __init__.py
        action.py
        mail.py
        mail_imap.py
        mail_applescript.py
    memory/
      __init__.py
      service.py     # MemoryService + MemoryStore (moved from core/)
    search/
      __init__.py
      service.py     # SearchService (refactored from core/search.py)
      providers.py   # DuckDuckGo, Searx, Google (extracted from search.py)
      config.py      # Search config re-exports
  gateway/
    __init__.py
    routes/
      __init__.py
      auth.py
      mail.py
      memory.py
      search.py
      chat.py
    middleware.py    # require_api_key, load_session
    session.py      # SessionStore (moved from core/session_store.py)
  core/             # Shared utilities only — no business logic
    config.py
    crypto.py
    llm.py
    docker.py
  agents/          # HeadAgent + subagents (stateless)
    head.py, mail.py, answer.py, command.py, base.py, __init__.py
```

**Not moved (still in `core/`):**
- `config.py` — shared config values
- `crypto.py` — encryption utilities used by auth
- `llm.py` — LLM adapter used by search and memory
- `docker.py` — sandbox execution for command agent
- `session_store.py` → `gateway/session.py`
- `db.py` — schema and migrations (consumed by service stores)

---

## Error Handling Pattern

Each service defines typed exception classes:

```python
# services/auth/errors.py
class AuthServiceError(Exception): pass
class UserExistsError(AuthServiceError): pass
class InvalidCredentialsError(AuthServiceError): pass

# services/mail/errors.py
class MailServiceError(Exception): pass
class NoActiveSessionError(MailServiceError): pass
class ImapConnectionError(MailServiceError): pass
```

The gateway maps service exceptions to HTTP:

```python
# gateway/routes/mail.py
from services.mail.errors import NoActiveSessionError, ImapConnectionError

except NoActiveSessionError:
    raise HTTPException(status_code=404, detail="No active mail session")
except ImapConnectionError as e:
    raise HTTPException(status_code=400, detail=str(e))
except MailServiceError:
    raise HTTPException(status_code=502, detail="Mail service error")
except Exception:
    raise HTTPException(status_code=500, detail="Internal server error")
```

This prevents a search timeout from crashing the whole server — each service's errors are contained.

---

## Session State Management

Sessions live in `SessionStore` (gateway-owned). The gateway loads a session and passes `SessionState` to service constructors:

```python
# gateway/routes/mail.py
session_id, state = _require_session(request)
service = MailService(state)
result = service.fetch(count=body.count, unread_only=body.unread_only, account=body.account)
state.mail_engine = service.to_dict()
save_session(state)
```

Services are **session-agnostic** — they receive a populated `SessionState` and return updated state. The gateway handles persistence.

---

## Interface Between Services

Services communicate via **interface classes (Protocol)** — the gateway uses them to type-hint service consumers without depending on concrete implementations:

```python
# services/interfaces.py
from typing import Protocol

class AuthServiceInterface(Protocol):
    def login(self, email: str, password: str) -> AuthResult: ...
    def get_user(self, user_id: str) -> User: ...

class MailServiceInterface(Protocol):
    def fetch(self, count: int, unread_only: bool, account: str) -> MailListResult: ...
    def move(self, indices: list[int], folder: str) -> str: ...
```

**Critical rule:** Services do NOT import each other. The gateway orchestrates. This keeps the dependency graph clean and prevents circular imports.

---

## Testing Strategy

Each service has its own test file:

```
tests/
  services/
    test_auth_service.py
    test_mail_service.py
    test_memory_service.py
    test_search_service.py
```

- **Unit tests** for each service use in-memory SQLite (or `pytest-mock` for external deps like Ollama)
- **Integration tests** in `tests/test_api.py` hit the gateway routes end-to-end
- Existing `tests/test_mail_engine.py`, `tests/test_crypto_db.py` are updated to import from new service paths
- `tests/test_session_store.py` moves to `tests/gateway/test_session.py`

---

## Migration Notes

All tables (`email_cache`, `memories`, `sessions`, `users`) already exist in `db.py` schema. No new migrations needed when services are stood up — each service simply starts using its already-owned tables.

## Migration Steps

1. Create `services/` and `gateway/` directory structure
2. Move/add service files one at a time, updating imports in `gateway/routes/`
3. Run tests after each move — everything should continue passing
4. Update `CLAUDE.md` and `README.md` to reflect new structure
5. Commit after each successful service move

The key constraint: **keep the server running and tests green after each step**.
