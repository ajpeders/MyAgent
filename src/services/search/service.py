"""Search service — web search and URL browsing. Owns no persistent data."""
import re
from html import unescape

from core.config import SEARCH_LLM_PROVIDER, SEARCH_LLM_MODEL, SEARCH_OPENAI_MODEL, SEARCH_ANTHROPIC_MODEL
from core.llm import default_adapter
from services.search.providers import get_provider, SearchResult


class SearchServiceError(Exception):
    pass


class ProviderTimeoutError(SearchServiceError):
    pass


class BrowseError(SearchServiceError):
    pass


def _llm_model() -> str:
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
    context = "\n".join(f"- {r.title}: {r.snippet}" for r in results[:5])
    messages = [
        {"role": "system", "content": "You are a helpful research assistant."},
        {
            "role": "user",
            "content": f"Based on these search results:\n{context}\n\nAnswer this question: {query}",
        },
    ]
    return default_adapter.complete(messages, schema={}, model=_llm_model())


class SearchService:
    """Web search with configurable provider and LLM answer generation."""

    def search(self, query: str) -> dict:
        """Search the web and return an answer + results list."""
        try:
            provider = get_provider()
            results = provider.search(query)
        except Exception as e:
            if "timeout" in str(e).lower():
                raise ProviderTimeoutError(f"Search provider timed out: {e}") from e
            raise SearchServiceError(f"Search provider error: {e}") from e

        if not results:
            return {"answer": "No results found.", "results": []}

        try:
            answer = _generate_answer(query, results)
        except Exception:
            answer = " ".join(r.snippet for r in results[:3])

        return {
            "answer": answer,
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in results
            ],
        }

    def browse(self, url: str) -> dict:
        """Fetch a URL and summarize its content via LLM."""
        import requests
        from readability import readability

        if not url.startswith(("http://", "https://")):
            raise BrowseError(f"Invalid URL: {url}")

        try:
            resp = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MyDevTeam/1.0)"},
            )
            resp.raise_for_status()
        except requests.Timeout:
            raise ProviderTimeoutError(f"Fetch timed out for {url}") from None
        except requests.RequestException as e:
            raise BrowseError(f"Fetch failed for {url}: {e}") from e

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            raise BrowseError(f"Non-HTML response ({content_type}) for {url}")

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
    return default_adapter.complete(messages, schema={}, model=_llm_model())