"""News curator — LLM-powered scoring and summarization of uncurated articles."""
import json
import logging

from src.services.llm.adapters import default_adapter
from src.services.news.service import NewsService
from src.services.news.store import NewsStore
from src.services.profile.service import ProfileService

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a personal news curator. Score each article 0-1 for relevance and write a 1-2 sentence summary for anything above 0.5.

User context:
- Interests: {interests}
- Today's calendar: {calendar_today}
- Key memories: {memories}
- Recent behavior: {recent_signals}
- Liked topics: {upvoted_topics}
- Disliked topics: {downvoted_topics}
- Preferred sources: {upvoted_sources}
- Deprioritized sources: {downvoted_sources}

Respond with JSON: {{"results": [{{"article_id": "...", "score": 0.85, "summary": "...", "reason": "..."}}]}}
Only include articles with score > 0.5."""

_CURATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "score": {"type": "number"},
                    "summary": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["article_id", "score"],
            },
        },
    },
    "required": ["results"],
}

_BATCH_SIZE = 20


class NewsCurator:
    def __init__(self) -> None:
        self._profile = ProfileService()
        self._news = NewsService()
        self._store = NewsStore()

    async def curate(self, user_id: str) -> int:
        """Score uncurated articles via LLM and save picks. Returns count of new picks."""
        # 1. Context
        snapshot = self._profile.context_snapshot(user_id)
        model = self._profile.get_model(user_id, "news_curation")

        # 2. Uncurated articles
        uncurated = self._store.get_uncurated_articles(user_id)
        if not uncurated:
            return 0

        # 3. Ratings for prompt context
        curated_ratings = self._store.get_curated_ratings(user_id)
        source_ratings = self._store.get_source_ratings(user_id)

        # 4. Build system prompt
        signals_summary = ", ".join(
            f"{s.signal_type}:{s.topic}" for s in snapshot.recent_signals[:10]
        )
        system_msg = _SYSTEM_PROMPT.format(
            interests=", ".join(snapshot.interests) or "none",
            calendar_today=", ".join(
                e.get("title", str(e)) for e in snapshot.calendar_today
            ) or "none",
            memories="; ".join(snapshot.memories[:5]) or "none",
            recent_signals=signals_summary or "none",
            upvoted_topics=", ".join(curated_ratings.get("upvoted", [])) or "none",
            downvoted_topics=", ".join(curated_ratings.get("downvoted", [])) or "none",
            upvoted_sources=", ".join(source_ratings.get("preferred", [])) or "none",
            downvoted_sources=", ".join(source_ratings.get("deprioritized", [])) or "none",
        )

        # 5. Batch and score
        total_picks = 0
        for i in range(0, len(uncurated), _BATCH_SIZE):
            batch = uncurated[i : i + _BATCH_SIZE]
            articles_payload = [
                {
                    "article_id": a["id"],
                    "title": a["title"],
                    "topic": a["topic"],
                    "summary": a.get("summary") or "",
                    "source": a.get("source_label", ""),
                }
                for a in batch
            ]

            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": json.dumps(articles_payload)},
            ]

            try:
                raw = default_adapter.complete_sync(messages, _CURATOR_SCHEMA, model)
                parsed = json.loads(raw)
            except Exception:
                log.warning("LLM curator call failed for batch %d", i, exc_info=True)
                continue

            results = parsed.get("results", [])
            for r in results:
                score = r.get("score", 0)
                if score < 0.5:
                    continue
                article_id = r.get("article_id", "")
                summary = r.get("summary", "")
                reason = r.get("reason", "")
                self._store.upsert_curated(user_id, article_id, summary, score, reason)
                total_picks += 1

        return total_picks
