"""Search providers — DuckDuckGo, Searx, Google. Extracted from core/search.py."""
from dataclasses import dataclass
from importlib import import_module

from src.core.config import SEARCH_PROVIDER, SEARCH_SEARX_URL, GOOGLE_API_KEY, GOOGLE_SEARCH_CX


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


PROVIDER_LABELS: dict[str, str] = {
    "duckduckgo": "DuckDuckGo",
    "searx": "Searx",
    "google": "Google Custom Search",
}


def _duckduckgo_client_class():
    """Support both legacy and current DuckDuckGo package module layouts."""
    for module_name in ("ddgs", "duckduckgo_search"):
        try:
            module = import_module(module_name)
        except ImportError:
            continue
        ddgs_class = getattr(module, "DDGS", None)
        if ddgs_class is not None:
            return ddgs_class
    raise ImportError("DuckDuckGo search dependency is unavailable. Install `duckduckgo-search`.")


class _DuckDuckGoProvider:
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        DDGS = _duckduckgo_client_class()

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


def list_available_providers() -> list[dict[str, str]]:
    return [
        {"id": provider_id, "label": label}
        for provider_id, label in PROVIDER_LABELS.items()
    ]


def get_provider(provider_name: str | None = None):
    """Return the configured search provider instance."""
    provider = (provider_name or SEARCH_PROVIDER).lower()
    if provider == "duckduckgo":
        return _DuckDuckGoProvider()
    elif provider == "searx":
        return _SearxProvider()
    elif provider == "google":
        return _GoogleProvider()
    else:
        raise ValueError(f"Unknown SEARCH_PROVIDER={provider!r}")
