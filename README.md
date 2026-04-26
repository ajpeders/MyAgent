# MyDevTeam

Personal local LLM agent with structured tool dispatch. Runs via Ollama (default: `qwen3:8b`).

## Quick Start

```bash
# Server
./start.sh
python -m src.gateway  # or: uvicorn src.gateway:app --reload

# Tests
.venv/bin/python -m pytest tests/ -v
```

### Web Frontend

The React + TypeScript frontend lives in `../MyWeb`. MyDevTeam exposes the FastAPI API only.

```bash
cd ../MyWeb && npm run dev    # Vite dev server on :5173, proxies /api to :8000
```

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — system diagram, design decisions, project layout, data flow, DB schema
- **[ROADMAP.md](ROADMAP.md)** — completed work, security audit status, planned features
- **[HOWTO.md](HOWTO.md)** — step-by-step guides for all common tasks (auth, IMAP, chat, memory, calendar, admin)

## API Endpoints

### Auth & Account
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/account/register` | Create user (email + password), returns JWT |
| POST | `/api/account/login` | Login, returns JWT with `user_id` (enc_key encrypted inside token) |
| POST | `/api/account/logout` | Logout and delete session |
| GET | `/api/account/me` | Get current user info (JWT required) |

### Config (IMAP)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/imap` | List IMAP accounts (metadata only) |
| POST | `/api/config/imap` | Add IMAP account (encrypted at rest) |
| GET | `/api/config/imap/{id}` | Get single IMAP account |
| PUT | `/api/config/imap/{id}` | Update IMAP account |
| DELETE | `/api/config/imap/{id}` | Remove IMAP account |

*All `/api/config/*` endpoints require `Authorization: Bearer <JWT>` header.*

### Memory
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/memory` | Add a memory |
| GET | `/api/memory?q=<query>&top_k=5` | Semantic search memories (top_k max 100) |
| DELETE | `/api/memory/{memory_id}` | Delete a memory |

*All memory endpoints require `Authorization: Bearer <JWT>`.*

### Chat & Mail
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send prompt to agent (routes via HeadAgent) |
| POST | `/api/chat/stream` | SSE streaming version of `/api/chat` |
| GET | `/api/mail` | Get current inbox page |
| POST | `/api/mail/fetch` | Fetch inbox from IMAP into session |
| GET | `/api/mail/by-date?date=YYYY-MM-DD` | Emails on a single date |
| GET | `/api/mail/by-date?start=...&end=...` | Emails in a date range |
| GET | `/api/mail/{index}` | Read full email by page-relative index |
| POST | `/api/mail/move` | Move emails to folder (default Trash) |

*All chat and mail endpoints require `Authorization: Bearer <JWT>`.*

### Calendar
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/calendar/events?start=...&end=...` | List events in date range |
| POST | `/api/calendar/events` | Create event (`{ title, date, time?, description? }`) |
| DELETE | `/api/calendar/events/{id}` | Delete an event |

*All calendar endpoints require `Authorization: Bearer <JWT>`.*

### Search
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/search` | Search the web, returns conversational answer + results |
| GET | `/api/search/browse?url=<url>` | Fetch and summarize a URL via LLM |

### Admin
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stats` | User/session counts, DB size |
| GET | `/api/admin/users` | List all users |
| GET | `/api/admin/sessions` | List all sessions |
| DELETE | `/api/admin/users/{id}` | Delete user (cascades) |
| DELETE | `/api/admin/sessions/{id}` | Delete session |

*All admin endpoints require `Authorization: Bearer <JWT>` with `is_admin=true` AND `X-API-Key` header (when `MYDEVTEAM_API_KEY` is set). Users are auto-promoted to admin if their email matches `ADMIN_EMAILS`.*

## Config

See **[HOWTO.md](HOWTO.md#configure-environment)** for full environment variable reference.

See **[ROADMAP.md](ROADMAP.md)** for full roadmap and changelog.
