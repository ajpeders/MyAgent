# MyDevTeam

Personal local LLM agent with structured tool dispatch. See **README.md** for full architecture, roadmap, and changelog.

## Key Constraints

- Each agent gets a **scoped JSON schema** — it can only emit its own action types
- Agents return **plans** (ordered action lists), not single actions — the executor runs the queue
- Shell commands run in a **Docker sandbox**, never on host
- `executor.py` coordinates external work; `mail_engine.py` owns mail-specific fetch/move calls and LLM mail parsing
- Head agent is stateless — routing only, no conversation history
- Mail display and state changes are deterministic code. The LLM only classifies mail intent and recommendations with fresh context.
- All LLM calls go through `llm.default_adapter` — never call Ollama directly
- IMAP folder names are provider-specific — `_resolve_folder()` maps generic names (e.g. `Trash`) to actual paths (e.g. `[Gmail]/Trash`)
- IMAP credentials encrypted at rest (AES-256-GCM, PBKDF2 key derivation)

## Project Layout

```
src/
  services/        Logical service packages (auth, mail, memory, search)
    auth/          User identity, login, IMAP credential encryption
      service.py   AuthService — register, login, IMAP CRUD
      store.py     UserStore — users table access
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
  gateway/         FastAPI server — routes, middleware, session management
    __main__.py    FastAPI app entry point (python -m src.gateway)
    routes/        auth.py, memory.py, search.py, mail.py, chat.py
    session.py     SessionStore, SessionState — owns sessions table
    middleware.py  require_api_key, get_session_id, get_user_id
  core/            Shared utilities — no business logic
    config.py      All config values
    crypto.py      AES-256-GCM encryption, password hashing
    db.py          Schema (_init_schema, _connect) — all tables owned by services
    executor.py    Agent dispatch — routes prompts to subagents
    llm.py         LLM adapter (ollama/openai/anthropic)
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
# CLI
python cli.py chat "check my email"
python cli.py chat "check my email" --session mysession

# Server
./start.sh
python -m src.gateway  # or: uvicorn src.gateway:app --reload

# Tests
.venv/bin/python -m pytest tests/ -v
```
