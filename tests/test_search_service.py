"""Tests for SearchService and remaining provider coverage."""
from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib

from src.services.search.providers import (
    SearchResult,
    _SearxProvider,
    _GoogleProvider,
    get_provider,
)
from src.services.search.service import (
    BrowseError,
    ProviderTimeoutError,
    SearchService,
    SearchServiceError,
)


# ── Provider tests ──────────────────────────────────────────────


class TestSearxProvider:
    def test_parses_searx_json_response(self):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "results": [
                {"title": "Result 1", "url": "https://a.com", "content": "Snippet 1"},
                {"title": "Result 2", "url": "https://b.com", "content": "Snippet 2"},
            ]
        }

        with patch("requests.get", return_value=fake_resp):
            results = _SearxProvider().search("test query")

        assert len(results) == 2
        assert results[0].title == "Result 1"
        assert results[0].url == "https://a.com"
        assert results[0].snippet == "Snippet 1"

    def test_respects_max_results(self):
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "results": [
                {"title": f"R{i}", "url": f"https://{i}.com", "content": f"S{i}"}
                for i in range(20)
            ]
        }

        with patch("requests.get", return_value=fake_resp):
            results = _SearxProvider().search("test", max_results=3)

        assert len(results) == 3

    def test_handles_empty_results(self):
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"results": []}

        with patch("requests.get", return_value=fake_resp):
            results = _SearxProvider().search("nothing")

        assert results == []


class TestGoogleProvider:
    def test_parses_google_json_response(self):
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "items": [
                {"title": "Google Result", "link": "https://g.com", "snippet": "Google snippet"},
            ]
        }

        with patch("requests.get", return_value=fake_resp):
            results = _GoogleProvider().search("test query")

        assert len(results) == 1
        assert results[0].title == "Google Result"
        assert results[0].url == "https://g.com"
        assert results[0].snippet == "Google snippet"

    def test_handles_empty_items(self):
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {}

        with patch("requests.get", return_value=fake_resp):
            results = _GoogleProvider().search("nothing")

        assert results == []


class TestGetProvider:
    def test_raises_on_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown SEARCH_PROVIDER"):
            get_provider("bing")


# ── SearchService.search() tests ────────────────────────────────


class TestSearchServiceSearch:
    def _fake_results(self, n=3):
        return [
            SearchResult(title=f"Title {i}", url=f"https://{i}.com", snippet=f"Snippet {i}")
            for i in range(n)
        ]

    def test_returns_answer_and_results(self):
        svc = SearchService()
        fake_provider = MagicMock()
        fake_provider.search.return_value = self._fake_results()

        with (
            patch("src.services.search.service.get_provider", return_value=fake_provider),
            patch("src.services.search.service._generate_answer", return_value="LLM answer"),
        ):
            result = svc.search("test query", provider_name="duckduckgo")

        assert result["answer"] == "LLM answer"
        assert len(result["results"]) == 3
        assert result["results"][0]["title"] == "Title 0"

    def test_skip_answer_skips_llm(self):
        svc = SearchService()
        fake_provider = MagicMock()
        fake_provider.search.return_value = self._fake_results()

        with (
            patch("src.services.search.service.get_provider", return_value=fake_provider),
            patch("src.services.search.service._generate_answer") as mock_gen,
        ):
            result = svc.search("test", provider_name="duckduckgo", skip_answer=True)

        mock_gen.assert_not_called()
        assert result["answer"] == ""
        assert len(result["results"]) == 3

    def test_empty_results_returns_early(self):
        svc = SearchService()
        fake_provider = MagicMock()
        fake_provider.search.return_value = []

        with patch("src.services.search.service.get_provider", return_value=fake_provider):
            result = svc.search("nothing")

        assert result["answer"] == ""
        assert result["results"] == []

    def test_llm_failure_falls_back_to_snippets(self):
        svc = SearchService()
        fake_provider = MagicMock()
        fake_provider.search.return_value = self._fake_results(2)

        with (
            patch("src.services.search.service.get_provider", return_value=fake_provider),
            patch("src.services.search.service._generate_answer", side_effect=RuntimeError("LLM down")),
        ):
            result = svc.search("test")

        assert result["answer"] == "Snippet 0 Snippet 1"

    def test_provider_timeout_raises(self):
        svc = SearchService()
        fake_provider = MagicMock()
        fake_provider.search.side_effect = Exception("Connection timeout reached")

        with patch("src.services.search.service.get_provider", return_value=fake_provider):
            with pytest.raises(ProviderTimeoutError):
                svc.search("test")

    def test_provider_error_raises(self):
        svc = SearchService()
        fake_provider = MagicMock()
        fake_provider.search.side_effect = Exception("Rate limited")

        with patch("src.services.search.service.get_provider", return_value=fake_provider):
            with pytest.raises(SearchServiceError):
                svc.search("test")


# ── SearchService.browse() tests ────────────────────────────────


class TestSearchServiceBrowse:
    def _html_response(self, body="<html><body><p>Hello world</p></body></html>", content_type="text/html"):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = body
        resp.headers = {"Content-Type": content_type}
        return resp

    def test_returns_summary_for_html_page(self):
        svc = SearchService()

        with (
            patch("requests.get", return_value=self._html_response()),
            patch("src.services.search.service._browse_summarize", return_value="Page summary"),
        ):
            result = svc.browse("https://example.com")

        assert result["summary"] == "Page summary"
        assert result["url"] == "https://example.com"

    def test_rejects_invalid_url(self):
        svc = SearchService()

        with pytest.raises(BrowseError, match="Invalid URL"):
            svc.browse("ftp://bad.com")

    def test_rejects_non_html_response(self):
        svc = SearchService()

        with patch(
            "requests.get",
            return_value=self._html_response(content_type="application/json"),
        ):
            with pytest.raises(BrowseError, match="Non-HTML"):
                svc.browse("https://example.com/api")

    def test_timeout_raises_provider_timeout(self):
        svc = SearchService()

        with patch("requests.get", side_effect=requests_lib.Timeout("timed out")):
            with pytest.raises(ProviderTimeoutError):
                svc.browse("https://slow.com")

    def test_request_error_raises_browse_error(self):
        svc = SearchService()

        with patch("requests.get", side_effect=requests_lib.ConnectionError("refused")):
            with pytest.raises(BrowseError, match="Fetch failed"):
                svc.browse("https://down.com")

    def test_readability_failure_falls_back_to_raw_text(self):
        svc = SearchService()
        raw = "x" * 5000
        fake_resp = self._html_response(body=raw)

        with (
            patch("requests.get", return_value=fake_resp),
            patch("readability.readability.Document", side_effect=Exception("parse fail")),
            patch("src.services.search.service._browse_summarize", return_value="Raw summary") as mock_sum,
        ):
            result = svc.browse("https://example.com")

        call_text = mock_sum.call_args[0][0]
        assert len(call_text) == 4000
        assert result["summary"] == "Raw summary"
        assert result["title"] == "https://example.com"
