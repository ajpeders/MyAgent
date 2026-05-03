"""News store — owns news_sources and news_articles tables."""
import time
import uuid

from src.core.db import _connect


_migrated = False


def _ensure_tables() -> None:
    global _migrated
    if _migrated:
        return
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_sources (
            source_id   TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            label       TEXT NOT NULL,
            topic       TEXT NOT NULL,
            feed_url    TEXT NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_sources_user
        ON news_sources(user_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            article_id    TEXT PRIMARY KEY,
            source_id     TEXT NOT NULL,
            user_id       TEXT NOT NULL,
            title         TEXT NOT NULL,
            topic         TEXT NOT NULL,
            url           TEXT NOT NULL,
            published_at  TEXT NOT NULL,
            summary       TEXT,
            fetched_at    REAL NOT NULL,
            FOREIGN KEY (source_id) REFERENCES news_sources(source_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_articles_user_topic
        ON news_articles(user_id, topic)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_url_user
        ON news_articles(url, user_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS curated_articles (
            curated_id      TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            article_id      TEXT NOT NULL,
            summary         TEXT,
            relevance_score REAL,
            reason          TEXT,
            created_at      REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (article_id) REFERENCES news_articles(article_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS curated_ratings (
            rating_id   TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            curated_id  TEXT NOT NULL,
            rating      INTEGER NOT NULL,
            created_at  REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (curated_id) REFERENCES curated_articles(curated_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_curated_ratings_user_curated
        ON curated_ratings(user_id, curated_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_ratings (
            rating_id   TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            rating      INTEGER NOT NULL,
            created_at  REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES news_sources(source_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_source_ratings_user_source
        ON source_ratings(user_id, source_id)
    """)
    conn.commit()
    conn.close()
    _migrated = True


class NewsStore:
    # ── Sources ──────────────────────────────────────────

    def list_sources(self, user_id: str) -> list[dict]:
        _ensure_tables()
        conn = _connect()
        rows = conn.execute(
            "SELECT source_id, user_id, label, topic, feed_url, enabled, created_at "
            "FROM news_sources WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        conn.close()
        return [_source_row(r) for r in rows]

    def get_source(self, source_id: str, user_id: str) -> dict | None:
        _ensure_tables()
        conn = _connect()
        row = conn.execute(
            "SELECT source_id, user_id, label, topic, feed_url, enabled, created_at "
            "FROM news_sources WHERE source_id = ? AND user_id = ?",
            (source_id, user_id),
        ).fetchone()
        conn.close()
        return _source_row(row) if row else None

    def create_source(
        self, user_id: str, label: str, topic: str, feed_url: str,
    ) -> dict:
        _ensure_tables()
        source_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO news_sources (source_id, user_id, label, topic, feed_url, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (source_id, user_id, label, topic, feed_url, now),
        )
        conn.commit()
        conn.close()
        return {
            "id": source_id,
            "user_id": user_id,
            "label": label,
            "topic": topic,
            "feed_url": feed_url,
            "enabled": True,
            "created_at": now,
        }

    def update_source(self, source_id: str, user_id: str, enabled: bool) -> bool:
        _ensure_tables()
        conn = _connect()
        cursor = conn.execute(
            "UPDATE news_sources SET enabled = ? WHERE source_id = ? AND user_id = ?",
            (int(enabled), source_id, user_id),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()
        return updated

    def delete_source(self, source_id: str, user_id: str) -> bool:
        _ensure_tables()
        conn = _connect()
        cursor = conn.execute(
            "DELETE FROM news_sources WHERE source_id = ? AND user_id = ?",
            (source_id, user_id),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted

    # ── Articles ─────────────────────────────────────────

    def upsert_articles(self, user_id: str, source_id: str, articles: list[dict]) -> int:
        """Insert articles, skipping duplicates by URL. Returns count inserted."""
        _ensure_tables()
        if not articles:
            return 0
        conn = _connect()
        inserted = 0
        for a in articles:
            try:
                conn.execute(
                    "INSERT INTO news_articles "
                    "(article_id, source_id, user_id, title, topic, url, published_at, summary, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()), source_id, user_id,
                        a["title"], a["topic"], a["url"],
                        a["published_at"], a.get("summary"), time.time(),
                    ),
                )
                inserted += 1
            except Exception:
                pass  # duplicate URL — skip
        conn.commit()
        conn.close()
        return inserted

    def list_articles(
        self, user_id: str, topic: str | None = None,
        source_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        _ensure_tables()
        query = (
            "SELECT a.article_id, a.source_id, s.label, a.title, a.topic, "
            "a.url, a.published_at, a.summary "
            "FROM news_articles a "
            "JOIN news_sources s ON a.source_id = s.source_id "
            "WHERE a.user_id = ?"
        )
        params: list = [user_id]

        if topic:
            query += " AND a.topic = ?"
            params.append(topic)
        if source_id:
            query += " AND a.source_id = ?"
            params.append(source_id)

        query += " ORDER BY a.published_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = _connect()
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [_article_row(r) for r in rows]


    # ── Curated Articles ──────────────────────────────────

    def upsert_curated(
        self, user_id: str, article_id: str, summary: str, score: float, reason: str,
    ) -> dict:
        _ensure_tables()
        curated_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO curated_articles "
            "(curated_id, user_id, article_id, summary, relevance_score, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (curated_id, user_id, article_id, summary, score, reason, now),
        )
        conn.commit()
        conn.close()
        return {
            "curated_id": curated_id,
            "user_id": user_id,
            "article_id": article_id,
            "summary": summary,
            "relevance_score": score,
            "reason": reason,
            "created_at": now,
        }

    def list_curated(self, user_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
        _ensure_tables()
        conn = _connect()
        rows = conn.execute(
            "SELECT c.curated_id, c.article_id, c.summary, c.relevance_score, c.reason, "
            "c.created_at, a.title, a.url, a.topic, s.label "
            "FROM curated_articles c "
            "JOIN news_articles a ON c.article_id = a.article_id "
            "JOIN news_sources s ON a.source_id = s.source_id "
            "WHERE c.user_id = ? "
            "ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
        conn.close()
        return [
            {
                "curated_id": r[0],
                "article_id": r[1],
                "summary": r[2],
                "relevance_score": r[3],
                "reason": r[4],
                "created_at": r[5],
                "title": r[6],
                "url": r[7],
                "topic": r[8],
                "source_label": r[9],
            }
            for r in rows
        ]

    def get_uncurated_articles(self, user_id: str) -> list[dict]:
        _ensure_tables()
        conn = _connect()
        rows = conn.execute(
            "SELECT a.article_id, a.title, a.topic, a.summary, s.label "
            "FROM news_articles a "
            "JOIN news_sources s ON a.source_id = s.source_id "
            "LEFT JOIN curated_articles c ON a.article_id = c.article_id AND c.user_id = ? "
            "WHERE a.user_id = ? AND c.curated_id IS NULL",
            (user_id, user_id),
        ).fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "title": r[1],
                "topic": r[2],
                "summary": r[3],
                "source_label": r[4],
            }
            for r in rows
        ]

    def rate_curated(self, user_id: str, curated_id: str, rating: int) -> None:
        _ensure_tables()
        rating_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO curated_ratings "
            "(rating_id, user_id, curated_id, rating, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rating_id, user_id, curated_id, rating, now),
        )
        conn.commit()

        # Look up topic for profile signal
        row = conn.execute(
            "SELECT a.topic FROM curated_articles c "
            "JOIN news_articles a ON c.article_id = a.article_id "
            "WHERE c.curated_id = ?",
            (curated_id,),
        ).fetchone()
        conn.close()

        if row:
            from src.services.profile.store import ProfileStore
            ProfileStore().log_signal(user_id, "curated_rating", row[0], str(rating))

    def rate_source(self, user_id: str, source_id: str, rating: int) -> None:
        _ensure_tables()
        rating_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO source_ratings "
            "(rating_id, user_id, source_id, rating, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rating_id, user_id, source_id, rating, now),
        )
        conn.commit()
        conn.close()

    def get_curated_ratings(self, user_id: str) -> dict:
        _ensure_tables()
        conn = _connect()
        rows = conn.execute(
            "SELECT cr.rating, a.topic "
            "FROM curated_ratings cr "
            "JOIN curated_articles c ON cr.curated_id = c.curated_id "
            "JOIN news_articles a ON c.article_id = a.article_id "
            "WHERE cr.user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()
        upvoted = set()
        downvoted = set()
        for rating, topic in rows:
            if rating > 0:
                upvoted.add(topic)
            elif rating < 0:
                downvoted.add(topic)
        return {"upvoted": sorted(upvoted), "downvoted": sorted(downvoted)}

    def get_source_ratings(self, user_id: str) -> dict:
        _ensure_tables()
        conn = _connect()
        rows = conn.execute(
            "SELECT sr.rating, s.label "
            "FROM source_ratings sr "
            "JOIN news_sources s ON sr.source_id = s.source_id "
            "WHERE sr.user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()
        preferred = set()
        deprioritized = set()
        for rating, label in rows:
            if rating > 0:
                preferred.add(label)
            elif rating < 0:
                deprioritized.add(label)
        return {"preferred": sorted(preferred), "deprioritized": sorted(deprioritized)}


def _source_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "label": row[2],
        "topic": row[3],
        "feed_url": row[4],
        "enabled": bool(row[5]),
        "created_at": row[6],
    }


def _article_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "source_id": row[1],
        "source_label": row[2],
        "title": row[3],
        "topic": row[4],
        "url": row[5],
        "published_at": row[6],
        "summary": row[7],
    }
