"""Web search abstraction with pluggable providers."""
from dataclasses import dataclass
from typing import Literal

from src.core.config import (
    SEARCH_PROVIDER,
    SEARCH_SEARX_URL,
    GOOGLE_API_KEY,
    GOOGLE_SEARCH_CX,
    SEARCH_LLM_PROVIDER,
    SEARCH_LLM_MODEL,
    SEARCH_OPENAI_MODEL,
    SEARCH_ANTHROPIC_MODEL,
)
from src.services.llm.adapters import default_adapter

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
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    )
                )
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
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                )
            )
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
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                )
            )
        return results


# ── LLM answer generation ──────────────────────────────────────────────────────


def _llm_model() -> str:
    """Return the configured LLM model for search."""
    provider = SEARCH_LLM_PROVIDER.lower()
    if provider == "ollama":
        return SEARCH_LLM_MODEL
    elif provider == "openai":
        return SEARCH_OPENAI_MODEL
    elif provider == "anthropic":
        return SEARCH_ANTHROPIC_MODEL
    else:
        return "qwen3:8b"


def _generate_answer(query: str, results: list[SearchResult]) -> str:
    """Use the configured LLM to generate a conversational answer from search results."""
    context = "\n".join(f"- {r.title}: {r.snippet}" for r in results[:5])
    messages = [
        {"role": "system", "content": "You are a helpful research assistant."},
        {
            "role": "user",
            "content": f"Based on these search results:\n{context}\n\nAnswer this question: {query}",
        },
    ]
    return default_adapter.complete_sync(messages, schema={}, model=_llm_model())


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
    except Exception:
        # Fall back to raw snippets if LLM fails
        answer = " ".join(r.snippet for r in results[:3])

    return {
        "answer": answer,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ],
    }


# ── Browse ───────────────────────────────────────────────────────────────────


def browse_url(url: str) -> dict:
    """Fetch a URL and summarize its content via LLM.

    Raises:
        ValueError: if URL is invalid or non-HTML
        TimeoutError: if fetch times out
    """
    import re
    from html import unescape

    import requests
    from readability import readability

    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url}")

    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MyDevTeam/1.0)"},
        )
        resp.raise_for_status()
    except requests.Timeout:
        raise TimeoutError(f"Fetch timed out for {url}") from None
    except requests.RequestException as e:
        raise RuntimeError(f"Fetch failed for {url}: {e}") from e

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise ValueError(f"Non-HTML response ({content_type}) for {url}")

    try:
        doc = readability.Document(resp.text)
        text = doc.summary()
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = " ".join(text.split())
    except Exception:
        text = resp.text[:4000]

    text = text[:4000]
    title = doc.title() if hasattr(doc, "title") else url

    summary = _browse_summarize(text, url, title)

    return {"summary": summary, "url": url, "title": title}


def _browse_summarize(text: str, url: str, title: str) -> str:
    """Use LLM to summarize page content."""
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that summarizes web pages concisely.",
        },
        {
            "role": "user",
            "content": f"Summarize this page (URL: {url}, Title: {title}):\n\n{text[:3000]}",
        },
    ]
    return default_adapter.complete_sync(messages, schema={}, model=_llm_model())
