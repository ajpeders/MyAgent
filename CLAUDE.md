# MyDevTeam

Personal local LLM agent with structured tool dispatch. See **README.md** for full architecture, roadmap, and changelog.

## Key Constraints

- Each agent gets a **scoped JSON schema** — it can only emit its own action types
- `AgentExecutor` runs an async tool-calling loop via `LLMService.chat()` — LLM returns tool calls, executor runs them, feeds results back
- Shell commands run in a **Docker sandbox**, never on host
- `executor.py` coordinates the agent loop; `mail_engine.py` owns mail-specific fetch/move calls and LLM mail parsing
- Head agent is stateless — routing only, no conversation history
- Mail display and state changes are deterministic code. The LLM only classifies mail intent and recommendations with fresh context.
- All LLM calls go through `services/llm/` adapters — never call Ollama directly
- IMAP folder names are provider-specific — `_resolve_folder()` maps generic names (e.g. `Trash`) to actual paths (e.g. `[Gmail]/Trash`)
- IMAP credentials encrypted at rest (AES-256-GCM, PBKDF2 key derivation)
- JWT tokens contain AES-256-GCM encrypted sensitive fields (`enc_key`) — signed with HS256, sensitive payload is opaque

## Project Layout

```
src/
  services/        Logical service packages (auth, mail, memory, search)
    auth/          User identity, login, IMAP credential encryption
      service.py   AuthService — register, login, IMAP CRUD
      store.py     UserStore — uses shared DB from core/db.py
      models.py    Pydantic request/response models
      errors.py    AuthServiceError subtypes
    mail/          IMAP fetch, email display, move/delete
      service.py   MailService — thin wrapper over MailEngine
      errors.py    MailServiceError subtypes
    memory/        Per-user semantic facts with embeddings
      service.py   MemoryService + MemoryStore — owns memories table
    search/        Web search + URL browsing, configurable provider
      service.py   SearchService
      providers.py DuckDuckGo, Searx, Google providers
    calendar/      Per-user calendar events
      service.py   CalendarService — create, list, delete
      store.py     CalendarStore — owns calendar_events table
    llm/           LLM abstraction layer
      service.py   LLMService — chat, complete, embeddings, streaming
      adapters.py  Pluggable adapters (Ollama, OpenAI, Anthropic)
      models.py    ToolCall, ToolResult, Plan models
  gateway/         FastAPI server — routes, middleware, session management
    __main__.py    FastAPI app entry point (python -m src.gateway)
    routes/        auth.py, memory.py, search.py, mail.py, chat.py
    session.py     SessionStore, SessionState — uses shared DB from core/db.py
    middleware.py  require_api_key, jwt_required, get_token, get_session_id
  core/            Shared utilities — no business logic
    config.py      All config values
    crypto.py      AES-256-GCM encryption, password hashing
    jwt.py         JWT sign/verify (HS256, enc_key encrypted with AES-256-GCM)
    db.py          Schema (_init_schema, _connect) — all tables owned by services
    executor.py    AgentExecutor — async tool-calling loop via LLMService
    agents/        HeadAgent + subagents (stateless routing)
    tools/         Tool definitions, registry, JSON schema builder
    docker.py      Sandbox execution
tests/            pytest suite
```

## Adding a New Agent

1. Define tools in `tools/registry.py`
2. Subclass `AgentDef` in `agents/`
3. Register in `agents/__init__.py`
4. System prompt and schema are derived automatically

## Running

```bash
# Server
./start.sh
python -m src.gateway  # or: uvicorn src.gateway:app --reload

# Tests
.venv/bin/python -m pytest tests/ -v
```
