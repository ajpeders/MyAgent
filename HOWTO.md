# How-To Guides

## Run the Server

```bash
# Using start script
./start.sh

# Or directly
python -m src.gateway

# Or with auto-reload
uvicorn src.gateway.__main__:app --reload
```

Server runs on `http://localhost:8000`. Health check: `GET /health`.

## Run the Frontend

```bash
cd ../MyWeb && npm run dev    # Vite dev server on :5173, proxies /api to :8000
```

## Run Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

## Register and Login

```bash
# Register
curl -X POST http://localhost:8000/api/account/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'

# Login (returns JWT token plus server session id)
curl -X POST http://localhost:8000/api/account/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
# Response: {"user_id": "...", "session_id": "...", "token": "...", "account": "you@example.com"}
```

Save the `token` — all subsequent requests need it:
```bash
TOKEN="<your-jwt-token>"
SESSION_ID="<your-session-id>"
```

## Add an IMAP Account

```bash
curl -X POST http://localhost:8000/api/config/imap \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Gmail",
    "server": "imap.gmail.com",
    "port": 993,
    "username": "you@gmail.com",
    "imap_password": "your-app-password"
  }'
```

Credentials are encrypted at rest using your login password as the key.

## Chat with the Agent

```bash
# Stateless (no session)
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "what is 2+2?"}'

# With session (for mail, multi-turn)
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Session-ID: $SESSION_ID" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"check my email\", \"session_id\": \"$SESSION_ID\"}"
```

## Use the Memory API

```bash
# Add a memory
curl -X POST http://localhost:8000/api/memory \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "My favorite color is blue"}'

# Semantic search
curl "http://localhost:8000/api/memory?q=color&top_k=5" \
  -H "Authorization: Bearer $TOKEN"

# Delete
curl -X DELETE http://localhost:8000/api/memory/<memory_id> \
  -H "Authorization: Bearer $TOKEN"
```

## Use the Calendar API

```bash
# Create event
curl -X POST http://localhost:8000/api/calendar/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Team standup", "date": "2026-04-28", "time": "09:00"}'

# List events in range
curl "http://localhost:8000/api/calendar/events?start=2026-04-01&end=2026-04-30" \
  -H "Authorization: Bearer $TOKEN"

# Delete event
curl -X DELETE http://localhost:8000/api/calendar/events/<event_id> \
  -H "Authorization: Bearer $TOKEN"
```

## Use the News API

Personalized news feed — register RSS/Atom sources, refresh feeds, and read an LLM-curated For You list.

```bash
# Add a source (admin only)
curl -X POST http://localhost:8000/api/news/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "Hacker News", "topic": "tech", "feed_url": "https://news.ycombinator.com/rss"}'

# Pull fresh articles and read the curated feed
curl -X POST http://localhost:8000/api/news/refresh -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/api/news/curated?limit=20" -H "Authorization: Bearer $TOKEN"
```

## Use the Profile API

Stores interests, per-task model preferences, and usage signals that feed news curation and the CoreAgent system prompt.

```bash
# Get profile (interests + model config)
curl http://localhost:8000/api/profile -H "Authorization: Bearer $TOKEN"

# Replace interest tags
curl -X PUT http://localhost:8000/api/profile/interests \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interests": ["machine learning", "homelab", "hiking"]}'
```

## Use the Schedule API

List and edit the cron-style scheduled tasks the background `scheduler_loop` runs.

```bash
# List the user's tasks
curl http://localhost:8000/api/schedule -H "Authorization: Bearer $TOKEN"

# Enable/disable or re-cron a task
curl -X PUT http://localhost:8000/api/schedule/<task_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"schedule": "0 7 * * *", "enabled": true}'
```

## Configure Mail and Search Provider

`/api/config/mail` controls the model + free-text preferences used for mail summarization; `/api/config/search` chooses the web search backend.

```bash
# Set the mail model and preferences
curl -X PUT http://localhost:8000/api/config/mail \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mail_model": "qwen3:8b", "mail_preferences": "Surface receipts and travel; ignore newsletters."}'

# Switch search provider (validated against /api/config/search GET list)
curl -X PUT http://localhost:8000/api/config/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"search_provider": "duckduckgo"}'
```

## Add a New Agent

1. Define tools in `src/core/tools/registry.py`
2. Subclass `AgentDef` in `src/core/agents/`
3. Register in `src/core/agents/__init__.py`
4. System prompt and schema are derived automatically

## Add a New Web Tool

1. Create `../MyWeb/src/tools/<name>/` with a page component
2. Add entry to `../MyWeb/src/tools/registry.ts`
3. Add route in `../MyWeb/src/App.tsx`

## Configure Environment

Key env vars (set in shell or `.env`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_MODEL` | `qwen3:8b` | Ollama model name |
| `JWT_SECRET` | (required) | Secret for signing JWT tokens (min 32 bytes) |
| `JWT_EXPIRY_HOURS` | `168` | JWT token expiry (default: 7 days) |
| `MYDEVTEAM_API_KEY` | (empty) | API key for admin endpoint protection |
| `ADMIN_EMAILS` | (empty) | Comma-separated emails auto-promoted to admin |
| `IMAP_<NAME>_HOST/USER/PASS/PORT` | — | Config-based IMAP accounts |
| `ALLOWED_ORIGINS` | `*` | CORS origins |

## Admin Operations

Requires a JWT with `is_admin=true` and `X-API-Key` header (when `MYDEVTEAM_API_KEY` is set).

```bash
# Stats
curl http://localhost:8000/api/admin/stats \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: $MYDEVTEAM_API_KEY"

# List users
curl http://localhost:8000/api/admin/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: $MYDEVTEAM_API_KEY"

# Delete user (cascades sessions, memories, calendar)
curl -X DELETE http://localhost:8000/api/admin/users/<user_id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: $MYDEVTEAM_API_KEY"
```
