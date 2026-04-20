# MyDevTeam

Personal local LLM agent with structured tool dispatch. Runs via Ollama (default: `qwen3:8b`).

## Architecture

- **Entry points**: `cli.py` (Typer CLI), `server.py` (FastAPI)
- **Routing**: `HeadAgent` classifies intent → dispatches to scoped subagent (Mail, Command, Answer)
- **Planning**: Subagents return a `Plan` (list of `Action`s) — the executor processes them as a batch
- **Execution**: `executor.py` is the shared dispatch layer — all external calls go through it
- **Mail Engine**: `mail_engine.py` owns mail inbox state, display, pagination, recommendations, and index-based execution
- **LLM**: All calls go through `llm.default_adapter` — never call Ollama directly
- **Tools**: `tools/registry.py` defines all tools; `tools/schema.py` builds per-agent JSON schemas
- **State**: `session_store.py` (SQLite) for multi-turn; `memory.py` for persistent per-agent memory

## Key constraints

- Each agent gets a **scoped JSON schema** — it can only emit its own action types
- Agents return **plans** (ordered action lists), not single actions — the executor runs the queue
- Shell commands run in a **Docker sandbox**, never on host
- `executor.py` coordinates external work; `mail_engine.py` owns mail-specific fetch/move calls and LLM mail parsing
- Head agent is stateless — routing only, no conversation history
- Mail display and state changes are deterministic code. The LLM only classifies mail intent and recommendations with fresh context.
- Mail backend: IMAP (primary, cross-platform) with AppleScript fallback (macOS only)
- IMAP folder names are provider-specific — `_resolve_folder()` maps generic names (e.g. `Trash`) to actual paths (e.g. `[Gmail]/Trash`)

## Adding a new agent

1. Define tools in `tools/registry.py`
2. Subclass `AgentDef` in `agents/`
3. Register in `agents/__init__.py`
4. System prompt and schema are derived automatically

## Mail backends

- **IMAP** (`actions/mail_imap.py`): Primary backend, works cross-platform. Configured via env vars. Supports multiple accounts.
- **AppleScript** (`actions/mail_applescript.py`): macOS-only fallback. Requires Mail.app running.
- **Dispatcher** (`actions/mail.py`): Routes to IMAP if configured, else AppleScript.
- **MailEngine** (`mail_engine.py`): Stores the inbox cache in `SessionState`, renders lists, resolves page-relative indices to UIDs, and updates cache after moves/deletes.
- **Multi-account**: When multiple IMAP accounts are configured, the first interactive fetch asks which account to use. Each email carries its `account` field for targeted moves/deletes.

## Tracking

- **TODO.md**: Active tasks and outstanding work — check at session start, update as work completes
- **CHANGELOG.md**: Record of completed changes — append when finishing work

## Config

Env vars or `config.py`. See `config.py` for all options.

## Running

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

## Web Frontend

The React + TypeScript frontend lives in the sibling project `../MyWeb`. MyDevTeam exposes the FastAPI API only.

### Development

```bash
cd ../MyWeb && npm run dev    # Vite dev server on :5173, proxies /api to :8000
```

### Adding a new tool

1. Create `../MyWeb/src/tools/<name>/` with a page component
2. Add entry to `../MyWeb/src/tools/registry.ts`
3. Add route in `../MyWeb/src/App.tsx`
