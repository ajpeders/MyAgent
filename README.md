# MyAgent

Personal local LLM agent with structured tool dispatch. Runs via Ollama (default: `qwen3:8b`).

## Quick Start

```bash
# Server
./start.sh
python -m src.gateway  # or: uvicorn src.gateway.__main__:app --reload

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
| POST | `/api/account/register` | Create user, returns `{ user_id, session_id, token, account }` |
| POST | `/api/account/login` | Login, returns `{ user_id, session_id, token, account }` |
| POST | `/api/account/logout` | Logout and delete session |
| GET | `/api/account/me` | Get current user info (JWT required) |

### Config (IMAP, Mail, Search)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/imap` | List IMAP accounts (metadata only) |
| POST | `/api/config/imap` | Add IMAP account (encrypted at rest) |
| GET | `/api/config/imap/{id}` | Get single IMAP account |
| PUT | `/api/config/imap/{id}` | Update IMAP account |
| DELETE | `/api/config/imap/{id}` | Remove IMAP account |
| GET | `/api/config/mail` | Get mail model + preferences + available models |
| PUT | `/api/config/mail` | Update mail model and free-text preferences |
| GET | `/api/config/search` | Get current search provider + available providers |
| PUT | `/api/config/search` | Update search provider (validated against list) |

*All `/api/config/*` endpoints require `Authorization: Bearer <JWT>` header.*

### Legacy IMAP (redirects to `/api/config/imap`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/imap` | Legacy alias for `GET /api/config/imap` |
| POST | `/api/imap` | Legacy alias for `POST /api/config/imap` |
| DELETE | `/api/imap/{id}` | Legacy alias for `DELETE /api/config/imap/{id}` |

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

### News
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/news/sources` | List configured news sources for current user |
| POST | `/api/news/sources` | Add a news source (admin) |
| PUT | `/api/news/sources/{id}` | Enable/disable a source (admin) |
| DELETE | `/api/news/sources/{id}` | Remove a source (admin) |
| POST | `/api/news/sources/seed` | Seed default sources (admin) |
| GET | `/api/news/articles` | List ingested articles (filter by topic/source) |
| POST | `/api/news/refresh` | Re-fetch all enabled feeds, returns new-article count |
| GET | `/api/news/curated` | LLM-curated For You feed |
| POST | `/api/news/curate` | Run curator over fresh articles (admin) |
| POST | `/api/news/curated/{id}/rate` | Rate a curated article (thumbs up/down) |
| POST | `/api/news/sources/{id}/rate` | Rate a source for ranking signal |

### Profile
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/profile` | Get current user's interests + model config |
| PUT | `/api/profile/interests` | Replace interest tags |
| PUT | `/api/profile/models` | Update per-task LLM model config |
| POST | `/api/profile/signal` | Log a usage signal (view/like/dismiss) |

### Schedule
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/schedule` | List the user's scheduled tasks |
| PUT | `/api/schedule/{task_id}` | Update schedule cron or enabled flag |

### LLM (direct provider passthrough)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/llm/chat` | Agent-style chat with optional tool definitions |
| POST | `/api/llm/complete` | Structured completion against an optional JSON schema |
| POST | `/api/llm/embeddings` | Get embedding vector for a text input |

### Whisper (voice)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/whisper/transcribe` | Transcribe raw audio bytes; persists transcript |
| POST | `/api/whisper/agent` | Voice → single-shot agent: transcribe + pick one tool + reply (synchronous) |
| POST | `/api/whisper/agent/async` | Same as above but returns `202 + job_id` immediately; reply pushed via ntfy |
| GET | `/api/whisper/jobs/{id}` | Poll an async voice agent job |
| GET | `/api/whisper/transcripts` | List the user's saved transcripts (JWT only) |
| DELETE | `/api/whisper/transcripts/{id}` | Delete a transcript (JWT only) |

**Voice agent toolbox** (used by `/agent` and `/agent/async`): `save_note`, `recall_notes`, `create_event`, `list_events`, `read_mail`, `search_web`, `answer`. The LLM picks one based on the transcript, the server executes via the existing services, and returns a short spoken-language reply. `read_mail` requires a recent web login (caches your encryption key in memory for 24h).

*Both POST endpoints accept either `Authorization: Bearer <JWT>` or `X-Device-Token: whsk_…` (long-lived per-user token for iPhone Shortcuts). See [docs/WHISPER_SHORTCUT.md](docs/WHISPER_SHORTCUT.md).*

### Device tokens (auth for external integrations)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/device-token` | Create or rotate the user's device token (returns plaintext once) |
| GET | `/api/auth/device-token` | Get token metadata (exists, last4, created_at) |
| DELETE | `/api/auth/device-token` | Revoke the current device token |

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
