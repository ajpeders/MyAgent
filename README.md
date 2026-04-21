# MyDevTeam

Personal local LLM agent with structured tool dispatch. Runs via Ollama (default: `qwen3:8b`).

## Quick Start

```bash
# CLI
python cli.py chat "check my email"
python cli.py chat "check my email" --session mysession

# Server
./start.sh
uvicorn server:app --reload  # dev

# Tests
.venv/bin/python -m pytest tests/ -v
```

### Web Frontend

The React + TypeScript frontend lives in `../MyWeb`. MyDevTeam exposes the FastAPI API only.

```bash
cd ../MyWeb && npm run dev    # Vite dev server on :5173, proxies /api to :8000
```

## Architecture

```mermaid
graph TD
    subgraph Entry["Entry Points"]
        CLI["CLI<br/>cli.py"]
        HTTP["HTTP Server<br/>server.py"]
    end

    subgraph State["State Layer"]
        SESSIONS["data.db<br/>SQLite"]
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
        ADAPTER["LLMAdapter<br/>llm.py"]
        OLLAMA["Ollama<br/>(qwen3:8b)"]
    end

    subgraph External["External Systems"]
        IMAP["IMAP<br/>(multi-account)"]
        APPLEMAIL["Apple Mail<br/>(AppleScript fallback)"]
        DOCKER["Docker Sandbox"]
    end

    CLI --> SESSIONS
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

    EXECUTOR --> ADAPTER
    EXECUTOR --> MAILENGINE
    MAILENGINE --> ADAPTER
    HEAD --> ADAPTER
    ADAPTER --> OLLAMA

    MAILENGINE --> IMAP
    MAILENGINE --> APPLEMAIL
    EXECUTOR --> DOCKER
```

### Key Design Decisions

- **Entry points**: `cli/__main__.py` (Typer CLI), `server/__main__.py` (FastAPI)
- **Routing**: `HeadAgent` classifies intent, dispatches to scoped subagent (Mail, Command, Answer)
- **Plan-based execution**: Subagents return a `Plan` (ordered list of `Action`s) — the executor runs the full queue, avoiding re-interpretation loops
- **Mail Engine**: `mail_engine.py` owns inbox state, display, pagination, and execution deterministically. The LLM is only called for recommendations and intent parsing with fresh context (no history accumulates)
- **LLM**: All calls go through `llm.default_adapter` — never call Ollama directly
- **Tools**: `tools/registry.py` defines tools; `tools/schema.py` builds per-agent JSON schemas
- **State**: SQLite (`core/db.py`) for users, sessions, and encrypted email cache
- **Security**: IMAP credentials encrypted at rest with AES-256-GCM, keys derived from user password via PBKDF2

### Project Layout

```
src/
  cli/          Typer CLI entry point
  core/
    actions/    Action model + mail backends (IMAP, AppleScript)
    agents/     HeadAgent + subagents (Mail, Command, Answer)
    tools/      Tool definitions, registry, JSON schema builder
    config.py   Env-based configuration
    crypto.py   AES-GCM encryption for credentials at rest
    db.py       SQLite stores (users, sessions, email cache)
    executor.py Plan dispatch + MailEngine integration
    llm.py      Ollama adapter
    mail_engine.py  Hybrid mail engine (deterministic state + LLM intent parsing)
    memory.py   Per-agent persistent memory
    session_store.py  Session load/save bridge
  server/       FastAPI entry point + auth/IMAP/mail endpoints
tests/          pytest suite
docs/superpowers/
  specs/        Design specifications
  plans/        Implementation plans
```

### Mail Backends

- **IMAP** (`actions/mail_imap.py`): Primary backend, cross-platform. Configured via env vars or encrypted user credentials.
- **AppleScript** (`actions/mail_applescript.py`): macOS-only fallback for Mail.app.
- **Multi-account**: Multiple IMAP accounts supported. First fetch asks which account. Each email carries its `account` field for targeted moves/deletes.
- **Folder resolution**: Provider-specific — `Trash` maps to `[Gmail]/Trash` on Gmail, `Trash` on Yahoo, etc.

### Mail Flow

1. User says "check my email"
2. `MailEngine.fetch()` reads emails via IMAP and stores in session
3. `MailEngine.recommend()` calls LLM once to tag emails as keep/delete/save
4. `MailEngine.display()` renders the current page deterministically (no LLM)
5. User interacts: read, delete, next, previous, page N
6. `MailEngine.handle()` parses intent with current-page context, resolves page-relative indices to cached UIDs
7. Destructive actions return confirmation; confirmed moves update cache and redisplay
8. "done" clears the mail session

### Adding a New Agent

1. Define tools in `tools/registry.py`
2. Subclass `AgentDef` in `agents/`
3. Register in `agents/__init__.py`
4. System prompt and schema are derived automatically

### Adding a New Web Tool

1. Create `../MyWeb/src/tools/<name>/` with a page component
2. Add entry to `../MyWeb/src/tools/registry.ts`
3. Add route in `../MyWeb/src/App.tsx`

## API Endpoints

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/register` | Create user (email + password) |
| POST | `/api/login` | Login, returns session_id + decrypted IMAP accounts |
| POST | `/api/imap/add` | Add IMAP account (encrypted at rest) |

### Chat & Mail
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send prompt to agent (routes via HeadAgent) |
| POST | `/api/mail/fetch` | Fetch inbox into session mail engine |
| GET | `/api/mail/{index}` | Read full email by page-relative index |
| POST | `/api/mail/confirm` | Confirm pending destructive mail action |
| POST | `/api/search` | Search the web, returns conversational answer + results |
| GET | `/api/search/browse?url=<url>` | Fetch and summarize a URL via LLM |

### Admin
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/login` | Login as admin (username=admin, password=`$MYDEVTEAM_API_KEY`) |
| GET | `/api/admin/stats` | User/session counts, DB size (requires `X-API-Key`) |
| GET | `/api/admin/users` | List all users |
| GET | `/api/admin/sessions` | List all sessions |
| DELETE | `/api/admin/users/{id}` | Delete user (cascades) |
| DELETE | `/api/admin/sessions/{id}` | Delete session |

*All admin endpoints except login require `X-API-Key` header matching `MYDEVTEAM_API_KEY`.*

## Config

Env vars or `config.py`. Key vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_MODEL` | `qwen3:8b` | Ollama model name |
| `MYDEVTEAM_API_KEY` | (empty) | API key for server auth (empty = no auth) |
| `IMAP_<NAME>_HOST/USER/PASS/PORT` | — | Config-based IMAP accounts |
| `ALLOWED_ORIGINS` | `*` | CORS origins |
| `REDIS_URL` | `redis://localhost:6379` | (Reserved for future use) |

## Roadmap

### Done

- [x] Project rename: MyAgent to MyDevTeam
- [x] Directory reorganization: flat files to `src/core/`, `src/cli/`, `src/server/`
- [x] MailEngine: deterministic display, pagination, serialization
- [x] MailEngine: LLM recommendations + intent parsing
- [x] MailEngine: fetch, execute, handle entry point
- [x] MailEngine wired into executor, CLI, server
- [x] Multi-user auth: register/login with password hashing
- [x] IMAP credential encryption (AES-256-GCM at rest)
- [x] SQLite-backed user, session, and email cache stores
- [x] Structured mail API endpoints (GET/POST /api/mail/*)
- [x] Admin endpoints (stats, user/session management) with API key auth
- [x] Mail read endpoint (`GET /api/mail/:index`) for full email body
- [x] Admin page frontend (`../MyWeb`)

### In Progress

- [x] End-to-end testing of full login → IMAP → mail flow
- [ ] Redis for production session storage (future, optional)

### Planned

- [ ] Web tool suite frontend (`../MyWeb`)
- [x] Web search tool integration (configurable provider: DuckDuckGo/Searx/Google + configurable LLM: Ollama or external SOTA API)
- [x] Personal data tool (per-user semantic memory via embeddings)
- [ ] Rename repo/directory (Gitea: `MyAgent` → `MyDevTeam`, local dir rename)

## Changelog

### 2026-04-20

**Directory reorganization**
- Moved flat top-level Python files into `src/core/`, `src/cli/`, `src/server/`
- Added symlinks (`cli`, `core`, `server`) for backward compatibility

**MailEngine + auth system**
- Implemented hybrid mail engine: deterministic state/display, LLM for intent parsing
- Added user registration/login with PBKDF2 password hashing
- Added AES-256-GCM encryption for IMAP credentials at rest
- Added SQLite stores for users, sessions, email cache
- Added structured mail API endpoints
- Fixed CLI session loading for local (no-auth) mode

**Admin login endpoint**
- `POST /api/admin/login` accepts username=admin + password=`$MYDEVTEAM_API_KEY`
- Other admin endpoints still require `X-API-Key` header

**Admin & mail read endpoints**
- Added admin API endpoints (stats, users, sessions, delete) with API key auth
- Added `GET /api/mail/{index}` for reading full email body by page index
- Added confirm flow: pending actions stored in session DB between requests

**Renamed project: MyAgent to MyDevTeam**
- Updated all file references, env vars, Docker container names
- Historical plan docs left unchanged
