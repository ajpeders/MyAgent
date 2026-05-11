# mac-agent

A lightweight local LLM harness for macOS. Runs a small model (default: `qwen2.5:3b`) via Ollama with a structured action dispatch loop and Apple Mail integration.

## Two entry points

| Entry point | File | Description |
|---|---|---|
| CLI | `cli.py` | Typer CLI — stateless or multi-turn (`chat` command) |
| Web UI + API | `server.py` | FastAPI — chat UI at `/`, stateless or multi-turn |

## Architecture

```
cli.py / server.py  →  (stateless)   executor.py  →  LLM / External
                    →  (multi-turn)  sessions.db
                                          ↓ (no active agent)
                                       HeadAgent   →  routes to subagent
                                          ↓ (active agent)
                                       MailAgent    →  executor.py
                                       CommandAgent →  executor.py
                                       AnswerAgent  →  executor.py
                                          ↓
                                       executor.py  →  LLM / Apple Mail / Docker / Web / Personal Data
```

- **cli.py** — `chat` (stateless by default; `--session <id>` opts into multi-turn) and `mailboxes` commands.
- **server.py** — FastAPI server. Stateless (omit `session_id`) or multi-turn (provide `session_id`) via shared `sessions.db`.
- **executor.py** — Shared dispatch layer for all entry points and subagents. Calls the LLM, parses a `Plan`, and routes actions to the right handler (mail, command, web, etc.).
- **agents/head.py** — Stateless router. Classifies user intent → returns `AgentRoute(agent, intent)`. Only invoked when no active agent in session.
- **agents/mail.py**, **agents/command.py**, **agents/answer.py** — Subagent definitions. Each has a scoped tool set and its own persistent memory. Context accumulates per subagent per session.
- **actions/action.py** — Pydantic schemas: `Action`, `Plan` (list of Actions), `AgentRoute`. LLM output is always JSON-schema-enforced via Ollama `format=`.
- **actions/mail.py** — Apple Mail integration via AppleScript.
- **session_store.py** — SQLite-backed session persistence (`sessions.db`). Shared by CLI and HTTP. `SessionState` tracks active agent, per-agent contexts, inbox cache, and pending confirmations.
- **memory.py** — Per-agent persistent memory (`memory/<agent>.json`). Injected into each subagent's system prompt at context-init time.
- **docker.py** — Runs shell commands in a Docker sandbox for the `command` action type.
- **config.py** — Constants: `DEFAULT_MODEL`, `TARGET_MAILBOX`, `MAIL_SUMMARY_COUNT`, `HOST`, `PORT`, `API_KEY`, `ALLOWED_ORIGINS`.
- **llm.py** — `LLMAdapter` ABC + `OllamaAdapter`. All LLM calls go through `default_adapter.complete(messages, schema, model)`. Set `LLM_PROVIDER=ollama` (default) or add a new adapter class to swap providers.
- **tools/** — Standardised tool layer:
  - `defs.py` — `ToolDef` / `ParamDef` dataclasses (name, description, params).
  - `registry.py` — Every tool defined once (`MAIL_READ`, `COMMAND`, `ANSWER`, etc.) plus pre-built sets (`MAIL_TOOLS`, `COMMAND_TOOLS`, `ANSWER_TOOLS`).
  - `prompt.py` — `build_system_prompt(role, tools, memory, context)` → consistent markdown prompt used by every agent.
  - `schema.py` — `build_plan_schema(tools)` → dynamic JSON schema scoped to only the tools an agent has (narrows LLM output space per-agent).

## Action Types

| Action | CLI/API | Server |
|---|---|---|
| `answer`, `summary`, `warning` | ✓ | ✓ |
| `mail_read`, `mail_move`, `mail_save` | ✓ | ✓ |
| `ask_user`, `note`, `remember` | ✓ | ✓ |
| `command` (Docker sandbox) | ✓ | ✓ |
| `web_search`, `personal_data` (AnswerAgent stubs) | ✓ | ✓ |
| `misc` | ✓ (CLI stateless only) | — |
| `done` | ✓ | ✓ |

## Key Design Constraints

- Both CLI and HTTP support **stateless** (no session) and **multi-turn** (shared `sessions.db`) modes. CLI defaults to stateless; pass `--session <id>` to opt into multi-turn.
- In multi-turn mode, `HeadAgent` is only invoked when there is no active agent in the session. Once an agent is active, requests go directly to that subagent.
- `executor.py` is the shared dispatch layer — all entry points and subagents route through it. Never call external systems (mail, docker, LLM) directly from agents or entry points.
- All LLM calls go through `llm.default_adapter` — never call `ollama.chat()` directly. Swap providers by setting `LLM_PROVIDER` and adding an adapter to `llm.py`.
- Each agent produces a **scoped JSON schema** via `build_plan_schema(agent.tools)` so the LLM can only output action types that agent actually has. `CommandAgent` can't emit `mail_read`; `MailAgent` can't emit `command`.
- Each agent has its own persistent memory (`memory/<agent>.json`), injected fresh at context-init time. Memory is not part of conversation history.
- Adding a new agent: (1) define its tools in `tools/registry.py`, (2) subclass `AgentDef`, (3) register in `agents/__init__.py`. System prompt and schema are derived automatically.
- Shell commands always run in a **Docker sandbox**, never directly on the host.
- The head agent is always stateless — no conversation history, routing only.

## Running

```bash
# CLI — stateless
python cli.py chat "check my email"
python cli.py mailboxes

# CLI — multi-turn (persists to sessions.db)
python cli.py chat "check my email" --session mysession
python cli.py chat "move newsletters to Archive" --session mysession

# Simple API server (http.server)
python api.py serve

# Web UI + FastAPI server (outside-accessible)
./start.sh                           # binds 0.0.0.0:8000, no auth
MAC_AGENT_API_KEY=secret ./start.sh  # with API key protection
PORT=9000 ./start.sh                 # custom port

# Dev (localhost only)
uvicorn server:app --reload
```

## Outside Access (server.py)

- Binds to `0.0.0.0` by default — reachable on local network and, with port forwarding, from the internet.
- API key auth: set `MAC_AGENT_API_KEY` env var. Clients must send `X-API-Key: <key>` header (or `?api_key=<key>`). `/` and `/health` are always public.
- CORS: set `ALLOWED_ORIGINS=https://myapp.com,https://other.com` to restrict origins (default `*`).
- For internet exposure: forward port 8000 (or `$PORT`) on your router, or use a tunnel (ngrok, Cloudflare Tunnel).

## Config

Edit `config.py` or set env vars to change model, target mailbox, or email fetch count.

| Env var | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `MAC_AGENT_API_KEY` | `` (no auth) | API key for all non-root endpoints |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |
