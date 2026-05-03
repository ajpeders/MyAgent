import pytest
from src.services.news.store import NewsStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("src.core.db._schema_initialized", False)
    monkeypatch.setattr("src.core.db._schema_initialized_path", None)
    monkeypatch.setattr("src.services.news.store._migrated", False)
    monkeypatch.setattr("src.services.profile.store._migrated", False)
    from src.core.db import _connect
    conn = _connect()
    conn.execute(
        "INSERT INTO users VALUES ('u1', 'test@test.com', NULL, NULL, NULL, NULL, NULL, 0, 0, 0)"
    )
    conn.commit()
    conn.close()

    ns = NewsStore()
    # Seed a source and two articles
    ns.create_source("u1", "Ars Technica", "Tech", "https://ars.com/rss")
    sources = ns.list_sources("u1")
    source_id = sources[0]["id"]

    ns.upsert_articles("u1", source_id, [
        {
            "title": "Article One",
            "topic": "Tech",
            "url": "https://ars.com/1",
            "published_at": "2026-01-01T00:00:00Z",
            "summary": "Summary one",
        },
        {
            "title": "Article Two",
            "topic": "Science",
            "url": "https://ars.com/2",
            "published_at": "2026-01-02T00:00:00Z",
            "summary": "Summary two",
        },
    ])
    return ns, source_id


def _get_article_ids(store, source_id):
    articles = store.list_articles("u1")
    return [a["id"] for a in articles]


# ── upsert_curated + list_curated ────────────────────────


def test_upsert_and_list_curated(store):
    ns, source_id = store
    article_ids = _get_article_ids(ns, source_id)
    result = ns.upsert_curated("u1", article_ids[0], "AI summary", 0.95, "Matches Tech interest")
    assert result["curated_id"]
    assert result["article_id"] == article_ids[0]
    assert result["relevance_score"] == 0.95

    curated = ns.list_curated("u1")
    assert len(curated) == 1
    c = curated[0]
    assert c["title"] in ("Article One", "Article Two")
    assert c["url"].startswith("https://ars.com/")
    assert c["source_label"] == "Ars Technica"
    assert c["summary"] == "AI summary"
    assert c["reason"] == "Matches Tech interest"


# ── get_uncurated_articles ───────────────────────────────


def test_get_uncurated_articles(store):
    ns, source_id = store
    article_ids = _get_article_ids(ns, source_id)

    # Curate one article
    ns.upsert_curated("u1", article_ids[0], "curated", 0.8, "reason")

    uncurated = ns.get_uncurated_articles("u1")
    assert len(uncurated) == 1
    assert uncurated[0]["id"] == article_ids[1]
    assert uncurated[0]["source_label"] == "Ars Technica"


# ── rate_curated ─────────────────────────────────────────


def test_rate_curated_upsert(store):
    ns, source_id = store
    article_ids = _get_article_ids(ns, source_id)
    curated = ns.upsert_curated("u1", article_ids[0], "s", 0.9, "r")
    cid = curated["curated_id"]

    ns.rate_curated("u1", cid, 1)
    ns.rate_curated("u1", cid, -1)  # should replace

    ratings = ns.get_curated_ratings("u1")
    # Second rating replaced first, so only downvoted
    assert "Tech" in ratings["downvoted"] or "Science" in ratings["downvoted"]
    assert len(ratings["upvoted"]) == 0


def test_rate_curated_logs_profile_signal(store, monkeypatch):
    ns, source_id = store
    article_ids = _get_article_ids(ns, source_id)
    curated = ns.upsert_curated("u1", article_ids[0], "s", 0.9, "r")
    cid = curated["curated_id"]

    logged = []
    from src.services.profile.store import ProfileStore
    monkeypatch.setattr(
        ProfileStore, "log_signal",
        lambda self, uid, stype, topic, source: logged.append((uid, stype, topic, source)),
    )

    ns.rate_curated("u1", cid, 1)
    assert len(logged) == 1
    assert logged[0][0] == "u1"
    assert logged[0][1] == "curated_rating"
    assert logged[0][3] == "1"


# ── rate_source ──────────────────────────────────────────


def test_rate_source_upsert(store):
    ns, source_id = store
    ns.rate_source("u1", source_id, 1)
    ns.rate_source("u1", source_id, -1)  # should replace

    ratings = ns.get_source_ratings("u1")
    assert "Ars Technica" in ratings["deprioritized"]
    assert len(ratings["preferred"]) == 0


# ── get_curated_ratings ──────────────────────────────────


def test_get_curated_ratings_aggregation(store):
    ns, source_id = store
    article_ids = _get_article_ids(ns, source_id)

    c1 = ns.upsert_curated("u1", article_ids[0], "s1", 0.9, "r1")
    c2 = ns.upsert_curated("u1", article_ids[1], "s2", 0.8, "r2")

    ns.rate_curated("u1", c1["curated_id"], 1)
    ns.rate_curated("u1", c2["curated_id"], -1)

    ratings = ns.get_curated_ratings("u1")
    assert len(ratings["upvoted"]) >= 1
    assert len(ratings["downvoted"]) >= 1


# ── get_source_ratings ───────────────────────────────────


def test_get_source_ratings_aggregation(store):
    ns, source_id = store
    ns.rate_source("u1", source_id, 1)

    ratings = ns.get_source_ratings("u1")
    assert "Ars Technica" in ratings["preferred"]
    assert len(ratings["deprioritized"]) == 0
