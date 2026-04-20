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
  cli/          Typer CLI entry point
  core/
    actions/    Action model + mail backends (IMAP, AppleScript)
    agents/     HeadAgent + subagents (Mail, Command, Answer)
    tools/      Tool definitions, registry, JSON schema builder
    config.py, crypto.py, db.py, executor.py, llm.py, mail_engine.py, memory.py, session_store.py
  server/       FastAPI entry point + auth/IMAP/mail endpoints
tests/          pytest suite
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
uvicorn server:app --reload  # dev

# Tests
.venv/bin/python -m pytest tests/ -v
```
