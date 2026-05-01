"""News service — source management and RSS feed fetching."""
import logging
import re
from datetime import datetime, timezone
from html import unescape

import feedparser

from src.services.news.errors import SourceNotFoundError
from src.services.news.models import (
    VALID_TOPICS,
    NewsArticle,
    NewsSource,
)
from src.services.news.defaults import DEFAULT_SOURCES
from src.services.news.store import NewsStore

log = logging.getLogger(__name__)


class NewsService:
    def __init__(self):
        self._store = NewsStore()

    # ── Sources ──────────────────────────────────────────

    def list_sources(self, user_id: str) -> list[NewsSource]:
        rows = self._store.list_sources(user_id)
        return [NewsSource(**r) for r in rows]

    def create_source(
        self, user_id: str, label: str, topic: str, feed_url: str,
    ) -> NewsSource:
        if topic not in VALID_TOPICS:
            raise ValueError(f"Invalid topic: {topic}")
        row = self._store.create_source(user_id, label, topic, feed_url)
        return NewsSource(**row)

    def update_source(self, source_id: str, user_id: str, enabled: bool) -> NewsSource:
        if not self._store.update_source(source_id, user_id, enabled):
            raise SourceNotFoundError(f"Source {source_id} not found")
        row = self._store.get_source(source_id, user_id)
        return NewsSource(**row)

    def delete_source(self, source_id: str, user_id: str) -> None:
        if not self._store.delete_source(source_id, user_id):
            raise SourceNotFoundError(f"Source {source_id} not found")

    def seed_defaults(self, user_id: str) -> list[NewsSource]:
        """Insert curated default sources for user, skipping duplicates by feed URL."""
        existing = self._store.list_sources(user_id)
        existing_urls = {s["feed_url"] for s in existing}
        added = []
        for src in DEFAULT_SOURCES:
            if src["feed_url"] in existing_urls:
                continue
            row = self._store.create_source(
                user_id, src["label"], src["topic"], src["feed_url"],
            )
            added.append(NewsSource(**row))
        return added

    # ── Articles ─────────────────────────────────────────

    def list_articles(
        self, user_id: str, topic: str | None = None,
        source_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> list[NewsArticle]:
        rows = self._store.list_articles(user_id, topic, source_id, limit, offset)
        return [NewsArticle(**r) for r in rows]

    def refresh_feeds(self, user_id: str) -> int:
        """Fetch all enabled sources for user. Returns total new articles inserted."""
        sources = self._store.list_sources(user_id)
        total = 0
        for src in sources:
            if not src["enabled"]:
                continue
            try:
                articles = _parse_feed(src["feed_url"], src["topic"])
                count = self._store.upsert_articles(user_id, src["id"], articles)
                total += count
            except Exception:
                log.warning("Failed to fetch feed %s (%s)", src["label"], src["feed_url"], exc_info=True)
        return total


def _parse_feed(feed_url: str, topic: str) -> list[dict]:
    """Parse an RSS/Atom feed and return normalized article dicts."""
    feed = feedparser.parse(feed_url)
    articles = []
    for entry in feed.entries:
        link = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not link or not title:
            continue

        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
        else:
            published = datetime.now(timezone.utc).isoformat()

        summary = getattr(entry, "summary", None)
        if summary:
            summary = re.sub(r"<[^>]+>", "", summary)
            summary = unescape(summary).strip()
            if len(summary) > 500:
                summary = summary[:497] + "..."

        articles.append({
            "title": title,
            "topic": topic,
            "url": link,
            "published_at": published,
            "summary": summary,
        })
    return articles
