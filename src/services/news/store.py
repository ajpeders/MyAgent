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
