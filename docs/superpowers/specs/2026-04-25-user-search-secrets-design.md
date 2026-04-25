# User Search Secrets — Per-User Encrypted Search Config

**Date:** 2026-04-25
**Status:** Draft

## Problem

All search and LLM configuration is global (env vars in `config.py`). Every user gets the same provider, model, and credentials. Users need per-user search provider config and LLM model preferences, encrypted at rest.

## Design Decisions

- **No global fallback.** If a user hasn't configured search secrets, the API returns an error. The frontend handles the setup flow.
- **Category-based rows.** `user_secrets` stores one encrypted JSON blob per category per user. Search is the first category; future categories (e.g. `imap`, `llm`) can reuse the same table.
- **Sensitive data is always encrypted.** API keys, URLs, and credentials are stored via `encrypt_payload()` / `decrypt_payload()` using the user's password-derived key (from JWT `enc_key`).
- **SearchService becomes stateless.** It receives config as a parameter instead of reading global env vars.
- **Empty `enc_key` blocks secrets operations.** Registration creates tokens with `enc_key=""`. The secrets PUT endpoint rejects requests with empty `enc_key` (401). Users must log in (which sets `enc_key` to their password) before saving secrets.
- **Breaking change for search routes.** `POST /api/search` and `GET /api/search/browse` become JWT-required. Existing unauthenticated clients will get 401.

## Table

### New: `user_secrets`

```sql
CREATE TABLE IF NOT EXISTS user_secrets (
    user_id         TEXT NOT NULL,
    category        TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    updated_at      REAL NOT NULL,
    PRIMARY KEY (user_id, category),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
)
```

Categories (initially):
- `"search"` — search provider + LLM config

## Encrypted Payload

### Search secrets (`category = "search"`)

```json
{
    "provider": "duckduckgo|searx|google",
    "searx_url": "",
    "google_api_key": "",
    "google_search_cx": "",
    "llm_provider": "ollama|openai|anthropic",
    "llm_model": "",
    "llm_api_key": "",
    "llm_api_url": ""
}
```

`llm_api_key` and `llm_api_url` are required when `llm_provider` is `openai` or `anthropic`. Not needed for `ollama` (local).

### Serialization

`encrypt_payload()` returns a dict (`{salt, iv, data}` — base64 strings). This dict is serialized with `json.dumps().encode()` before storing in the `BLOB` column. On read, `json.loads()` restores the dict before passing to `decrypt_payload()`.

## Service Layer

### New: `services/secrets/service.py` — SecretsService

Owns the `user_secrets` table. Pure encryption/storage, no business logic.

```python
class SecretsService:
    def get(user_id: str, category: str, enc_key: str) -> dict | None
    def set(user_id: str, category: str, data: dict, enc_key: str) -> None
    def delete(user_id: str, category: str) -> bool
```

### New: `services/secrets/errors.py`

```python
class SecretsError(Exception): pass
class SecretNotFoundError(SecretsError): pass
class DecryptionError(SecretsError): pass
class EmptyEncKeyError(SecretsError): pass
```

### Changes to existing services

- **SearchService** — `search(query, search_config)` and `browse(url, search_config)` take a config dict instead of reading globals. Raises `SearchConfigRequired` if no config passed. The `_generate_answer()` and `_browse_summarize()` helpers receive LLM config (provider, model, api_key, api_url) from the search config and pass them to `LLMService.complete()`.
- **Search providers** — `get_provider(config)` takes a config dict. Provider classes accept config in constructor: `_SearxProvider(searx_url)`, `_GoogleProvider(api_key, search_cx)`, `_DuckDuckGoProvider()`. The `search()` methods use constructor values, not globals.

## API Endpoints

All require JWT auth (`jwt_required`). New route file: `gateway/routes/secrets.py`.

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `GET` | `/api/secrets/{category}` | — | Get decrypted secrets (API keys masked) |
| `PUT` | `/api/secrets/{category}` | JSON payload | Create or update secrets |
| `DELETE` | `/api/secrets/{category}` | — | Delete secrets |

### Validation (search category)

On PUT with `category = "search"`:
- `provider` must be one of `duckduckgo`, `searx`, `google`
- If `searx` — `searx_url` required
- If `google` — `google_api_key` and `google_search_cx` required
- `llm_provider` must be one of `ollama`, `openai`, `anthropic`
- `llm_model` required
- If `llm_provider` is `openai` or `anthropic` — `llm_api_key` required

### Request Models

```python
class SearchSecrets(BaseModel):
    provider: Literal["duckduckgo", "searx", "google"]
    searx_url: str = ""
    google_api_key: str = ""
    google_search_cx: str = ""
    llm_provider: Literal["ollama", "openai", "anthropic"]
    llm_model: str
    llm_api_key: str = ""
    llm_api_url: str = ""
```

### Masking on GET

GET responses mask sensitive fields — show last 4 characters only:
- `google_api_key` → `"****abcd"`
- `llm_api_key` → `"****efgh"`

Non-sensitive fields (`provider`, `llm_provider`, `llm_model`, `searx_url`, `llm_api_url`, `google_search_cx`) are returned in full.

## Request Flow

### Search request (new flow)

```
POST /api/search  (JWT required)
  → middleware extracts user_id + enc_key from JWT
  → route handler:
      1. secrets_service.get(user_id, "search", enc_key) → config or 400
      2. search_service.search(query, config)
```

### Browse request (new flow)

```
GET /api/search/browse?url=...  (JWT required)
  → middleware extracts user_id + enc_key from JWT
  → route handler:
      1. secrets_service.get(user_id, "search", enc_key) → config or 400
      2. search_service.browse(url, config)
```

### Error responses

- `400 {"error": "search_not_configured"}` — no search secrets for user
- `401 {"error": "decryption_failed"}` — enc_key wrong (re-login needed)
- `422` — validation failure on PUT (Pydantic)

## File Changes

### New files
- `src/services/secrets/__init__.py`
- `src/services/secrets/service.py`
- `src/services/secrets/errors.py`
- `src/gateway/routes/secrets.py`

### Modified files
- `src/services/auth/store.py` — add `user_secrets` table to `_init_schema`
- `src/services/search/service.py` — parameterize instead of reading globals
- `src/services/search/providers.py` — `get_provider()` takes config dict
- `src/gateway/__main__.py` — register secrets router
- `src/gateway/routes/search.py` — resolve user secrets before calling service, require JWT auth
