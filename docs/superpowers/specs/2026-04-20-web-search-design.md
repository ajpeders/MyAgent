# Web Search Tool — Implementation Spec

## Overview

Add a web search capability to MyDevTeam via a `web_search` tool and `/search` frontend page. The agent can search the web and return conversational answers; users can also browse results directly.

## Architecture

```
User prompt → executor.dispatch_session()
  → web_search action → POST /api/search → configurable provider (DuckDuckGo, Searx, Google)
                      → Ollama (configurable) → answer + results
                                           → browse summary
```

## Configurable Search Providers

In `config.py`:
```python
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "duckduckgo")  # "duckduckgo" | "searx" | "google"
SEARCH_SEARX_URL = os.environ.get("SEARCH_SEARX_URL", "")           # Self-hosted Searx instance
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX", "")
```

Each provider is a class implementing:
```python
def search(query: str, max_results: int = 10) -> list[SearchResult]:
    ...

class SearchResult:
    title: str
    url: str
    snippet: str
```

## Backend

### `POST /api/search`

**Request:**
```json
{"query": "latest Python 3.14 features"}
```

**Response:**
```json
{
  "answer": "Python 3.14 is scheduled for release in October 2024...",
  "results": [
    {"title": "Python 3.14 Release Schedule", "url": "https://docs.python.org/3.14...", "snippet": "Python 3.14.0 release schedule..."},
    ...
  ]
}
```

**Behavior:**
1. Route query to configured search provider
2. Build a context string from top 5 result snippets
3. Send to LLM: "Based on these search results: [context]\n\nAnswer: {query}"
4. Return `{answer, results}`

**Error handling:**
- Provider timeout → 504 with `{"detail": "Search provider timed out"}`
- Provider error → 502 with `{"detail": "Search provider error: <msg>"}`
- No results → `{"answer": "No results found.", "results": []}`

### `GET /api/search/browse`

**Request:** `GET /api/search/browse?url=https%3A%2F%2Fexample.com`

**Response:**
```json
{"summary": "This page describes...", "url": "https://example.com", "title": "Example Domain"}
```

**Behavior:**
1. Fetch URL, extract readable text (strip ads/nav/scripts via `readability` or similar)
2. Truncate to ~4000 tokens
3. Send to LLM: "Summarize this page: {text}"
4. Return `{summary, url, title}`

**Error handling:**
- Invalid URL → 400
- Fetch timeout → 504
- Non-HTML response → 422

## LLM Backend (Configurable)

In `config.py`:
```python
SEARCH_LLM_PROVIDER = os.environ.get("SEARCH_LLM_PROVIDER", "ollama")  # "ollama" | "openai" | "anthropic"
SEARCH_LLM_MODEL    = os.environ.get("SEARCH_LLM_MODEL", "qwen3:8b")
SEARCH_OPENAI_MODEL = os.environ.get("SEARCH_OPENAI_MODEL", "gpt-4o-mini")
SEARCH_ANTHROPIC_MODEL = os.environ.get("SEARCH_ANTHROPIC_MODEL", "claude-sonnet-4-6")
```

Each call uses the same `llm.py` adapter interface, just with a different provider.

## Executor Wiring

In `executor.py`, the `web_search` action type:
```python
elif action.type == ActionType.web_search:
    results.append({"type": "answer", "content": f"Web search not yet implemented. Query: {action.content}", "agent": agent_name})
```

Replace with a call to the search service returning `answer` type with the full response content.

## Frontend

### `SearchPage.tsx`

- Search input bar at top
- Results list: title (link), snippet, source domain
- Click result → modal or inline panel showing LLM summary from browse API
- Accessible at `/search`

### Chat Integration

- When agent returns `answer` from web search, chat UI displays it inline
- No separate streaming needed for v1

## Dependencies

- `duckduckgo-search>=6.0` — no API key required (default provider)
- ` Searxng` — self-hosted metasearch (if `SEARCH_PROVIDER=searx`)
- `google-api-python-client` — if `SEARCH_PROVIDER=google`
- `readability-lxml` or `trafilatura` — URL content extraction
- `openai` / `anthropic` — optional external LLM (already have SDKs)

## File Changes

| File | Change |
|------|--------|
| `src/core/search.py` | New — search provider abstraction + browse + LLM routing |
| `src/core/config.py` | Add `SEARCH_PROVIDER`, `SEARCH_LLM_*` env vars |
| `src/core/executor.py` | Wire `web_search` action to search service |
| `src/server/__main__.py` | Add `POST /api/search`, `GET /api/search/browse` |
| `MyWeb/src/tools/search/SearchPage.tsx` | New page component |
| `MyWeb/src/tools/registry.ts` | Add search tool entry |
| `MyWeb/src/App.tsx` | Add `/search` route |
| `README.md` | Document search API endpoints |

## Testing

1. `POST /api/search` with a query → returns answer + results array
2. `GET /api/search/browse` with a URL → returns summary
3. Chat prompt "search for X" → agent returns answer type with content
4. `/search` page → renders results list, click result shows summary
