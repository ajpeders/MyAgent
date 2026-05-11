"""Tests for DuckDuckGo provider compatibility imports."""
import sys
import types

import pytest

from src.services.search.providers import _DuckDuckGoProvider, _duckduckgo_client_class


class _FakeDDGS:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def text(self, query: str, max_results: int = 10):
        assert query == "search contract"
        assert max_results == 10
        return [
            {
                "title": "Search API",
                "href": "https://example.com/search-api",
                "body": "POST /api/search returns results.",
            },
        ]


def test_duckduckgo_client_class_falls_back_to_duckduckgo_search(monkeypatch):
    monkeypatch.delitem(sys.modules, "ddgs", raising=False)
    monkeypatch.setitem(sys.modules, "duckduckgo_search", types.SimpleNamespace(DDGS=_FakeDDGS))

    assert _duckduckgo_client_class() is _FakeDDGS


def test_duckduckgo_provider_uses_compatible_ddgs_import(monkeypatch):
    monkeypatch.delitem(sys.modules, "ddgs", raising=False)
    monkeypatch.setitem(sys.modules, "duckduckgo_search", types.SimpleNamespace(DDGS=_FakeDDGS))

    results = _DuckDuckGoProvider().search("search contract")

    assert len(results) == 1
    assert results[0].title == "Search API"
    assert results[0].url == "https://example.com/search-api"
    assert results[0].snippet == "POST /api/search returns results."


def test_duckduckgo_client_class_raises_clear_error_when_dependency_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "ddgs", raising=False)
    monkeypatch.delitem(sys.modules, "duckduckgo_search", raising=False)

    real_import = __import__("importlib").import_module

    def fake_import(name: str, package=None):
        if name in {"ddgs", "duckduckgo_search"}:
            raise ImportError(name)
        return real_import(name, package)

    monkeypatch.setattr("src.services.search.providers.import_module", fake_import)

    with pytest.raises(ImportError, match="duckduckgo-search"):
        _duckduckgo_client_class()
