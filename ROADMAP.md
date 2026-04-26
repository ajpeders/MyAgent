# Roadmap

## Done

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
- [x] End-to-end testing of full login → IMAP → mail flow
- [x] Service architecture: auth, mail, memory, search services with FastAPI gateway
- [x] Calendar service with per-user event CRUD

### Security Audit (2026-04-25)

All 9 issues identified and fixed, 3 test coverage gaps filled.

**Critical (fixed)**
- [x] Auth bypass: chat/mail/memory routes trust `X-User-ID` header with no JWT validation
- [x] `enc_key` (plaintext password) persisted to SQLite sessions table
- [x] `require_api_key` middleware defined but never registered
- [x] Split SQLite databases with divergent schema — cross-DB foreign keys silently fail
- [x] `import asyncio` after use in `services/llm/service.py`

**Important (fixed)**
- [x] `asyncio.run()` called inside running event loop
- [x] Dead import `_dispatch_plan` in `chat.py`
- [x] `add_imap_account` encode/decode logic inconsistent with login decoder
- [x] Unbounded `top_k` in memory search endpoint

**Test coverage (filled)**
- [x] IMAP credential add/update/delete round-trip tests
- [x] Auth bypass regression tests
- [x] Cross-user data isolation tests

## Planned

- [ ] Web tool suite frontend (`../MyWeb`)
- [ ] Redis for session storage (optional/future — SQLite WAL mode sufficient for now)

## Changelog

### 2026-04-25 — Security Audit

Full backend audit identified 9 issues (5 critical, 4 important) and 3 test coverage gaps. All fixed.
- **Auth bypass**: replaced `X-User-ID` header trust with JWT validation on all routes
- **Plaintext password in DB**: removed `enc_key` from sessions table (lives only in encrypted JWT)
- **Split databases**: consolidated 3 SQLite files into single `src/core/data.db`
- **Runtime errors**: fixed asyncio import ordering, event loop nesting, dead import
- **IMAP credentials**: fixed inconsistent encode/decode, clamped memory `top_k`
- **Tests**: added 16 new tests (IMAP CRUD, auth bypass regression, cross-user isolation)

### 2026-04-25

**JWT security hardening**
- Encrypted sensitive JWT fields (enc_key) with AES-256-GCM inside the token
- Added `RuntimeError` guard on `jwt.decode()` when `JWT_SECRET` is empty

**Import cleanup + test fixes**
- Fixed ~50 stale imports across codebase left over from service architecture refactor
- Rewrote e2e tests for new `AgentExecutor` architecture

**JWT Auth + Config Endpoints**
- Replaced `session_id` with signed JWT tokens
- Added `/api/config/imap` endpoints (CRUD, encrypted at rest)

**Service Architecture**
- Split monolith into `services/auth`, `services/mail`, `services/memory`, `services/search`, `services/llm`
- FastAPI gateway with typed error classes mapped to HTTP

### 2026-04-20

- Directory reorganization: flat files to `src/core/`, `src/cli/`, `src/server/`
- Hybrid mail engine: deterministic state/display, LLM for intent parsing
- User registration/login with PBKDF2 password hashing
- AES-256-GCM encryption for IMAP credentials at rest
- Admin API endpoints with API key auth
- Project rename: MyAgent to MyDevTeam
