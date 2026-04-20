# Web Search Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/search`, `GET /api/search/browse`, and `/search` frontend page. The agent's `web_search` action calls the API and returns a conversational answer.

**Architecture:** Configurable search provider (DuckDuckGo/Searx/Google) → LLM generates answer from snippets. Separate browse endpoint fetches URLs and summarizes via LLM. Provider and LLM backend both pluggable via env vars.

**Tech Stack:** `duckduckgo-search`, `readability-lxml`, existing `llm.py` adapter pattern, FastAPI endpoints, React frontend.

---

## Chunk 1: Config + Search Provider Abstraction

**Files:**
- Modify: `src/core/config.py`
- Create: `src/core/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Add config vars to config.py**

Add to `src/core/config.py` after the IMAP section:

```python
# Search provider: "duckduckgo" | "searx" | "google"
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "duckduckgo")
SEARCH_SEARX_URL = os.environ.get("SEARCH_SEARX_URL", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX", "")

# LLM backend for search answers (ollama | openai | anthropic)
SEARCH_LLM_PROVIDER = os.environ.get("SEARCH_LLM_PROVIDER", "ollama")
SEARCH_LLM_MODEL = os.environ.get("SEARCH_LLM_MODEL", "qwen3:8b")
SEARCH_OPENAI_MODEL = os.environ.get("SEARCH_OPENAI_MODEL", "gpt-4o-mini")
SEARCH_ANTHROPIC_MODEL = os.environ.get("SEARCH_ANTHROPIC_MODEL", "claude-sonnet-4-6")
```

Run: `python -c "from core.config import SEARCH_PROVIDER, SEARCH_LLM_PROVIDER; print(SEARCH_PROVIDER, SEARCH_LLM_PROVIDER)"`
Expected: `duckduckgo ollama`

- [ ] **Step 2: Write failing test for search.py**

Create `tests/test_search.py`:

```python
"""Tests for core.search module."""
import pytest
from unittest.mock import patch, MagicMock

from core.search import SearchResult, search_web


def test_search_result_fields():
    r = SearchResult(title="Test", url="https://example.com", snippet="A snippet")
    assert r.title == "Test"
    assert r.url == "https://example.com"
    assert r.snippet == "A snippet"


@patch("core.search._get_provider")
def test_search_returns_answer_and_results(mock_get_provider):
    mock_provider = MagicMock()
    mock_provider.search.return_value = [
        SearchResult(title="t", url="https://x.com", snippet="s")
    ]
    mock_get_provider.return_value = mock_provider

    result = search_web("test query")
    assert "answer" in result
    assert "results" in result
    assert len(result["results"]) == 1
```

Run: `pytest tests/test_search.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create search.py with provider interface**

Create `src/core/search.py`:

```python
"""Web search abstraction with pluggable providers."""
import os
import time
from dataclasses import dataclass
from typing import Literal

from core.config import (
    SEARCH_PROVIDER, SEARCH_SEARX_URL, GOOGLE_API_KEY, GOOGLE_SEARCH_CX,
    SEARCH_LLM_PROVIDER, SEARCH_LLM_MODEL, SEARCH_OPENAI_MODEL, SEARCH_ANTHROPIC_MODEL,
)
from core.llm import default_adapter

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


# ── Provider implementations ───────────────────────────────────────────────────


def _get_provider():
    """Return the configured search provider instance."""
    provider = SEARCH_PROVIDER.lower()
    if provider == "duckduckgo":
        return _DuckDuckGoProvider()
    elif provider == "searx":
        return _SearxProvider()
    elif provider == "google":
        return _GoogleProvider()
    else:
        raise ValueError(f"Unknown SEARCH_PROVIDER={provider!r}")


class _DuckDuckGoProvider:
    """Uses duckduckgo-search Python package."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                ))
        return results


class _SearxProvider:
    """Uses a self-hosted Searx instance."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        import requests
        url = SEARCH_SEARX_URL.rstrip("/") + "/search"
        params = {"q": query, "format": "json", "engines": "google"}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            ))
        return results


class _GoogleProvider:
    """Uses Google Custom Search JSON API."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        import requests
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_SEARCH_CX,
            "q": query,
            "num": min(max_results, 10),
        }
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("items", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
            ))
        return results


# ── LLM answer generation ──────────────────────────────────────────────────────


def _generate_answer(query: str, results: list[SearchResult]) -> str:
    """Use the configured LLM to generate a conversational answer from search results."""
    context = "\n".join(
        f"- {r.title}: {r.snippet}" for r in results[:5]
    )
    messages = [
        {"role": "system", "content": "You are a helpful research assistant."},
        {"role": "user", "content": f"Based on these search results:\n{context}\n\nAnswer this question: {query}"},
    ]

    # Use the configured LLM provider
    provider = SEARCH_LLM_PROVIDER.lower()
    if provider == "ollama":
        model = SEARCH_LLM_MODEL
    elif provider == "openai":
        model = SEARCH_OPENAI_MODEL
    elif provider == "anthropic":
        model = SEARCH_ANTHROPIC_MODEL
    else:
        model = "qwen3:8b"

    return default_adapter.complete(messages, schema={}, model=model)


# ── Public API ────────────────────────────────────────────────────────────────


def search_web(query: str) -> dict:
    """Search the web and return an answer + results list.

    Raises:
        TimeoutError: if the provider times out
        Exception: on provider errors
    """
    try:
        provider = _get_provider()
        results = provider.search(query)
    except Exception as e:
        if "timeout" in str(e).lower():
            raise TimeoutError(f"Search provider timed out: {e}") from e
        raise RuntimeError(f"Search provider error: {e}") from e

    if not results:
        return {"answer": "No results found.", "results": []}

    try:
        answer = _generate_answer(query, results)
    except Exception as e:
        # Fall back to raw snippets if LLM fails
        answer = " ".join(r.snippet for r in results[:3])

    return {
        "answer": answer,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ],
    }
```

Run: `pytest tests/test_search.py -v`
Expected: FAIL — config vars not in scope in test (patch path issue)

- [ ] **Step 4: Run test — fix import path in test mock**

Update test to patch at correct module path. Run again.
Expected: Tests pass or adjust mock paths.

- [ ] **Step 5: Add pytest marker and install deps**

Check `pyproject.toml` has `duckduckgo-search` and `readability-lxml` in dependencies. Add if missing:

```toml
dependencies = [
    ...
    "duckduckgo-search>=6.0",
    "readability-lxml>=0.8",
    "requests>=2.31",
]
```

Run: `pip install duckduckgo-search readability-lxml`
Expected: No error

- [ ] **Step 6: Commit**

```bash
git add src/core/config.py src/core/search.py tests/test_search.py pyproject.toml
git commit -m "feat: add search provider abstraction and DuckDuckGo support"
```

---

## Chunk 2: Browse Endpoint

**Files:**
- Modify: `src/core/search.py` (add `browse_url`)
- Create: `tests/test_search.py` (add browse tests)

- [ ] **Step 1: Write failing test for browse**

Add to `tests/test_search.py`:

```python
def test_browse_url():
    from core.search import browse_url
    # Mock the LLM call
    with patch("core.search._browse_summarize") as mock_summarize:
        mock_summarize.return_value = "Page summary"
        result = browse_url("https://example.com")
        assert result["summary"] == "Page summary"
        assert result["url"] == "https://example.com"
```

Run: `pytest tests/test_search.py::test_browse_url -v`
Expected: FAIL — browse_url not defined

- [ ] **Step 2: Implement browse_url in search.py**

Add to `src/core/search.py`:

```python
def browse_url(url: str) -> dict:
    """Fetch a URL and summarize its content via LLM.

    Raises:
        ValueError: if URL is invalid
        TimeoutError: if fetch times out
    """
    import requests
    from readability import readability
    from html import unescape
    import re

    # Validate URL
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url}")

    # Fetch
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MyDevTeam/1.0)"
        })
        resp.raise_for_status()
    except requests.Timeout:
        raise TimeoutError(f"Fetch timed out for {url}") from None
    except requests.RequestException as e:
        raise RuntimeError(f"Fetch failed for {url}: {e}") from e

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise ValueError(f"Non-HTML response ({content_type}) for {url}")

    # Extract readable text
    try:
        doc = readability.Document(resp.text)
        text = doc.summary()
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = " ".join(text.split())
    except Exception:
        text = resp.text[:4000]  # fallback to raw text

    # Truncate
    text = text[:4000]

    # Summarize via LLM
    summary = _browse_summarize(text, url)

    return {
        "summary": summary,
        "url": url,
        "title": doc.title() if "doc" in dir() else url,
    }


def _browse_summarize(text: str, url: str) -> str:
    """Use LLM to summarize page content."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant that summarizes web pages."},
        {"role": "user", "content": f"Summarize this page (URL: {url}):\n\n{text[:3000]}"},
    ]
    provider = SEARCH_LLM_PROVIDER.lower()
    if provider == "ollama":
        model = SEARCH_LLM_MODEL
    elif provider == "openai":
        model = SEARCH_OPENAI_MODEL
    elif provider == "anthropic":
        model = SEARCH_ANTHROPIC_MODEL
    else:
        model = "qwen3:8b"
    return default_adapter.complete(messages, schema={}, model=model)
```

Run: `pytest tests/test_search.py::test_browse_url -v`
Expected: PASS (or FAIL on LLM call — mock if needed)

- [ ] **Step 3: Commit**

```bash
git add src/core/search.py tests/test_search.py
git commit -m "feat: add browse_url with readability extraction and LLM summarization"
```

---

## Chunk 3: FastAPI Endpoints

**Files:**
- Modify: `src/server/__main__.py` (add endpoints)
- Create: `tests/test_search_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_search_api.py`:

```python
"""API tests for search endpoints."""
import pytest
from fastapi.testclient import TestClient

def test_search_requires_session():
    # Skip auth for now — search should work without session
    pass

def test_search_returns_answer_and_results():
    # Will fill in after endpoint exists
    pass
```

- [ ] **Step 2: Add search endpoints to server/__main__.py**

Add to `src/server/__main__.py`:

```python
from core.search import search_web, browse_url


class SearchRequest(BaseModel):
    query: str


class SearchResultResponse(BaseModel):
    title: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    answer: str
    results: list[SearchResultResponse]


class BrowseResponse(BaseModel):
    summary: str
    url: str
    title: str | None


@app.post("/api/search", response_model=SearchResponse)
def api_search(req: SearchRequest):
    """Search the web and return a conversational answer + results list."""
    try:
        result = search_web(req.query)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail="Search provider timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Search provider error: {e}")

    return SearchResponse(
        answer=result["answer"],
        results=[
            SearchResultResponse(title=r["title"], url=r["url"], snippet=r["snippet"])
            for r in result["results"]
        ],
    )


@app.get("/api/search/browse", response_model=BrowseResponse)
def api_browse(request: Request, url: str):
    """Fetch a URL and summarize its content via LLM."""
    try:
        result = browse_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Fetch timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Browse error: {e}")

    return BrowseResponse(
        summary=result["summary"],
        url=result["url"],
        title=result.get("title"),
    )
```

Restart server and test manually:
```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"what is python"}' | python3 -m json.tool
```

Expected: JSON with answer + results

- [ ] **Step 3: Commit**

```bash
git add src/server/__main__.py
git commit -m "feat: add POST /api/search and GET /api/search/browse endpoints"
```

---

## Chunk 4: Executor Wiring

**Files:**
- Modify: `src/core/executor.py`

- [ ] **Step 1: Replace the web_search stub with a real call**

In `src/core/executor.py`, replace line ~233:
```python
elif action.type == ActionType.web_search:
    results.append({"type": "web_search", "content": f"Web search not yet implemented. Query: {action.content}", "agent": agent_name})
```

With:
```python
elif action.type == ActionType.web_search:
    from core.search import search_web
    try:
        result = search_web(action.content)
        answer_text = result["answer"]
        if result["results"]:
            answer_text += "\n\n**Web Results:**\n" + "\n".join(
                f"- [{r['title']}]({r['url']})" for r in result["results"][:5]
            )
    except TimeoutError:
        answer_text = "Search timed out. Please try again."
    except Exception as e:
        answer_text = f"Search failed: {e}"
    results.append({"type": "answer", "content": answer_text, "agent": agent_name})
```

Test with:
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "X-Session-ID: $SESSION_ID" -H "X-User-ID: $USER_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"search for what is docker"}'
```

Expected: Returns answer with web results

- [ ] **Step 2: Commit**

```bash
git add src/core/executor.py
git commit -m "feat: wire web_search action to search service"
```

---

## Chunk 5: Frontend SearchPage

**Files:**
- Create: `MyWeb/src/tools/search/SearchPage.tsx`
- Modify: `MyWeb/src/tools/registry.ts`
- Modify: `MyWeb/src/App.tsx`

- [ ] **Step 1: Create SearchPage.tsx**

Following the pattern of `MailPage.tsx` and `AdminPage.tsx`:

```tsx
import { useState } from "react";
import { chatFetch } from "../api/chat";

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<SearchResult | null>(null);
  const [summary, setSummary] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setSelected(null);
    setSummary("");
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      setAnswer(data.answer || "");
      setResults(data.results || []);
    } catch (err) {
      setAnswer("Search failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleResultClick = async (r: SearchResult) => {
    setSelected(r);
    setSummaryLoading(true);
    try {
      const res = await fetch(`/api/search/browse?url=${encodeURIComponent(r.url)}`);
      const data = await res.json();
      setSummary(data.summary || "Could not summarize.");
    } catch {
      setSummary("Failed to load summary.");
    } finally {
      setSummaryLoading(false);
    }
  };

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">Web Search</h1>
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          className="flex-1 border rounded px-3 py-2"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search the web..."
        />
        <button type="submit" className="px-4 py-2 bg-blue-600 text-white rounded" disabled={loading}>
          {loading ? "..." : "Search"}
        </button>
      </form>

      {answer && (
        <div className="p-4 bg-gray-50 rounded border">
          <p className="whitespace-pre-wrap">{answer}</p>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          {results.map((r, i) => (
            <div key={i} className="p-3 border rounded hover:bg-gray-50 cursor-pointer" onClick={() => handleResultClick(r)}>
              <a href={r.url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-600 hover:underline" onClick={e => e.stopPropagation()}>
                {r.title}
              </a>
              <p className="text-sm text-gray-600 mt-1">{r.snippet}</p>
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div className="p-4 border rounded bg-white mt-4">
          <h2 className="font-bold mb-2">Summary: {selected.title}</h2>
          {summaryLoading ? <p>Loading summary...</p> : <p className="whitespace-pre-wrap">{summary}</p>}
          <a href={selected.url} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-600 mt-2 inline-block">
            Open original →
          </a>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add to registry**

In `MyWeb/src/tools/registry.ts`:

```ts
{
  name: "Search",
  path: "/search",
  description: "Search the web and browse pages",
},
```

- [ ] **Step 3: Add route to App.tsx**

Add to the router in `MyWeb/src/App.tsx`:

```tsx
import SearchPage from "./tools/search/SearchPage";
// ...
<Route path="/search" element={<SearchPage />} />
```

- [ ] **Step 4: Test the page**

Navigate to `http://localhost:5173/search`, search for something, click a result.

- [ ] **Step 5: Commit**

```bash
git add MyWeb/src/tools/search/SearchPage.tsx MyWeb/src/tools/registry.ts MyWeb/src/App.tsx
git commit -m "feat: add /search page with results list and URL summarization"
```

---

## Chunk 6: README Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add search API endpoints to README**

Add to the API Endpoints table in README.md under "Chat & Mail":

```markdown
| POST | `/api/search` | Search the web, returns answer + results |
| GET | `/api/search/browse?url=<url>` | Summarize a URL |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add search API endpoints to README"
```
