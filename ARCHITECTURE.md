# Architecture

## System Diagram

```mermaid
graph TD
    subgraph Entry["Entry Points"]
        HTTP["HTTP Server<br/>gateway"]
    end

    subgraph State["State Layer"]
        SESSIONS["core/data.db<br/>SQLite (single DB)"]
    end

    subgraph Routing["Routing"]
        HEAD["HeadAgent<br/>head.py"]
    end

    subgraph Agents["Subagents (plan-based)"]
        MAIL["MailAgent<br/>(mail tools)"]
        CMD["CommandAgent<br/>(command tools)"]
        ANS["AnswerAgent<br/>(answer tools)"]
    end

    subgraph Execution["Execution"]
        EXECUTOR["executor.py<br/>plan queue processor"]
        MAILENGINE["MailEngine<br/>mail_engine.py"]
    end

    subgraph LLM["LLM"]
        LLMSVC["LLMService<br/>services/llm"]
        ADAPTER["LLMAdapter<br/>adapters.py"]
        OLLAMA["Ollama<br/>(qwen3:8b)"]
    end

    subgraph External["External Systems"]
        IMAP["IMAP<br/>(multi-account)"]
        APPLEMAIL["Apple Mail<br/>(AppleScript fallback)"]
        DOCKER["Docker Sandbox"]
    end

    HTTP --> SESSIONS
    SESSIONS -->|"no active agent"| HEAD
    SESSIONS -->|"active agent"| MAIL
    SESSIONS -->|"active agent"| CMD
    SESSIONS -->|"active agent"| ANS
    HEAD --> MAIL
    HEAD --> CMD
    HEAD --> ANS

    MAIL --> EXECUTOR
    CMD --> EXECUTOR
    ANS --> EXECUTOR

    EXECUTOR --> LLMSVC
    EXECUTOR --> MAILENGINE
    MAILENGINE --> ADAPTER
    HEAD --> ADAPTER
    LLMSVC --> ADAPTER
    ADAPTER --> OLLAMA

    MAILENGINE --> IMAP
    MAILENGINE --> APPLEMAIL
    EXECUTOR --> DOCKER
```

## Key Design Decisions

- **Service architecture**: Code split into logical service packages (`auth`, `mail`, `memory`, `search`) with a thin FastAPI gateway. Each service owns its tables, exposes typed error classes, and communicates via Protocol interfaces.
- **Entry point**: `gateway/__main__.py` (FastAPI)
- **Routing**: `HeadAgent` classifies intent, dispatches to scoped subagent (Mail, Command, Answer)
- **Execution**: `AgentExecutor` runs an async tool-calling loop via `LLMService.chat()` — the LLM returns tool calls, executor runs them, feeds results back
- **Mail Engine**: `src/core/mail_engine.py` owns inbox state, display, pagination, and execution deterministically. The LLM is only called for recommendations and intent parsing with fresh context (no history accumulates)
- **LLM**: All calls go through `services/llm/` adapters (Ollama, OpenAI, Anthropic) — never call providers directly
- **JWT auth**: Tokens contain `user_id` and an AES-256-GCM encrypted `enc_key` (user's password). Sensitive fields are encrypted inside the JWT so intercepting the token reveals nothing.
- **Tools**: `tools/registry.py` defines tools; `tools/schema.py` builds per-agent JSON schemas
- **State**: Single SQLite database (`src/core/data.db`) for all tables — users, sessions, memories, calendar events, and encrypted email cache. All modules use `core/db._connect()`. Foreign keys enforced within the single DB.
- **Security**: All routes (except register/login) require JWT. Admin endpoints require JWT `is_admin` + API key. IMAP credentials encrypted at rest with AES-256-GCM, keys derived from user password via PBKDF2. `enc_key` exists only in the encrypted JWT — never persisted to disk.

## Project Layout

```
src/
  services/        Logical service packages — each owns its tables
    auth/          User identity, login, IMAP credential encryption
      service.py   AuthService — register, login, IMAP account CRUD
      store.py     UserStore — uses shared DB from core/db.py
      models.py    Pydantic models (AuthResult, ImapAccount, etc.)
      errors.py    AuthServiceError subtypes
    mail/          IMAP fetch, email display, move/delete
      service.py   MailService — thin wrapper over MailEngine
      errors.py    MailServiceError subtypes
    memory/        Per-user semantic facts with embeddings
      service.py   MemoryService + MemoryStore — owns memories table
    search/        Web search + URL browsing
      service.py   SearchService — search() and browse()
      providers.py DuckDuckGo, Searx, Google providers
    calendar/      Per-user calendar events
      service.py   CalendarService — create, list, delete
      store.py     CalendarStore — owns calendar_events table
      models.py    CreateEventRequest, CalendarEvent
      errors.py    EventNotFoundError
    llm/           LLM abstraction layer
      service.py   LLMService — chat, complete, embeddings, streaming
      adapters.py  Pluggable adapters (Ollama, OpenAI, Anthropic)
      models.py    ToolCall, ToolResult, Plan models
      errors.py    ProviderError, TimeoutError
  gateway/         FastAPI server — routes, middleware, session management
    __main__.py    App entry point (python -m src.gateway)
    routes/        auth, memory, search, mail, chat
    session.py     SessionStore, SessionState — uses shared DB from core/db.py
    middleware.py  require_api_key, jwt_required, get_token, get_session_id
  core/            Shared utilities — no business logic
    config.py      Env-based configuration
    crypto.py      AES-GCM encryption for credentials at rest
    jwt.py         JWT sign/verify with encrypted sensitive fields
    db.py          Schema (_init_schema, _connect) — consumed by services
    executor.py    AgentExecutor — async tool-calling loop via LLMService
    mail_engine.py Hybrid mail engine (deterministic state + LLM intent parsing)
    agents/        HeadAgent + subagents (stateless routing)
    tools/         Tool definitions, registry, JSON schema builder
    docker.py      Sandbox execution
tests/          pytest suite
docs/superpowers/
  specs/        Design specifications
  plans/        Implementation plans
```

## Data Flow

### Authentication

1. User registers or logs in via `/api/account/*`
2. Server returns a signed JWT containing `user_id` and AES-256-GCM encrypted `enc_key`
3. All subsequent requests include `Authorization: Bearer <JWT>`
4. `jwt_required()` middleware validates the token and extracts `user_id`
5. Admin endpoints additionally check `is_admin` flag and `X-API-Key` header

### Mail Flow

1. User says "check my email"
2. `MailEngine.fetch()` reads emails via IMAP and stores in session
3. `MailEngine.recommend()` calls LLM once to tag emails as keep/delete/save
4. `MailEngine.display()` renders the current page deterministically (no LLM)
5. User interacts: read, delete, next, previous, page N
6. `MailEngine.handle()` parses intent with current-page context, resolves page-relative indices to cached UIDs
7. Destructive actions return confirmation; confirmed moves update cache and redisplay
8. "done" clears the mail session

### Mail Backends

- **IMAP** (`actions/mail_imap.py`): Primary backend, cross-platform. Configured via env vars or encrypted user credentials.
- **AppleScript** (`actions/mail_applescript.py`): macOS-only fallback for Mail.app.
- **Multi-account**: Multiple IMAP accounts supported. First fetch asks which account. Each email carries its `account` field for targeted moves/deletes.
- **Folder resolution**: Provider-specific — `Trash` maps to `[Gmail]/Trash` on Gmail, `Trash` on Yahoo, etc.

## Database Schema

Single SQLite database at `src/core/data.db`. All tables created by `core/db._init_schema()`.

| Table | Owner | Description |
|-------|-------|-------------|
| `users` | `auth/store.py` | User accounts with password hashes and encrypted IMAP creds |
| `sessions` | `gateway/session.py` | Per-user sessions with mail engine state |
| `memories` | `memory/service.py` | Per-user semantic facts with embedding vectors |
| `calendar_events` | `calendar/store.py` | Per-user calendar events |
| `email_cache` | `core/db.py` | Encrypted email cache per user/account/mailbox |

All tables use `FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE`.
