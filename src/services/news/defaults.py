"""Curated default news sources across all topics."""

DEFAULT_SOURCES: list[dict] = [
    # ── Tech ─────────────────────────────────────────────
    {
        "label": "Ars Technica",
        "topic": "Tech",
        "feed_url": "https://feeds.arstechnica.com/arstechnica/index",
    },
    {
        "label": "TechCrunch",
        "topic": "Tech",
        "feed_url": "https://techcrunch.com/feed/",
    },
    {
        "label": "Hacker News",
        "topic": "Tech",
        "feed_url": "https://hnrss.org/frontpage",
    },
    {
        "label": "Tom's Hardware",
        "topic": "Tech",
        "feed_url": "https://www.tomshardware.com/feeds/all",
    },

    # ── Music ────────────────────────────────────────────
    {
        "label": "Stereogum",
        "topic": "Music",
        "feed_url": "https://www.stereogum.com/feed/",
    },
    {
        "label": "Consequence of Sound",
        "topic": "Music",
        "feed_url": "https://consequence.net/feed/",
    },
    {
        "label": "NME",
        "topic": "Music",
        "feed_url": "https://www.nme.com/feed",
    },

    # ── World ────────────────────────────────────────────
    {
        "label": "Reuters World",
        "topic": "World",
        "feed_url": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
    },
    {
        "label": "Associated Press World",
        "topic": "World",
        "feed_url": "https://rsshub.app/apnews/topics/apf-WorldNews",
    },
    {
        "label": "BBC World",
        "topic": "World",
        "feed_url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },

    # ── US News ──────────────────────────────────────────
    {
        "label": "Associated Press",
        "topic": "US News",
        "feed_url": "https://rsshub.app/apnews/topics/apf-usnews",
    },
    {
        "label": "Reuters US",
        "topic": "US News",
        "feed_url": "https://www.reutersagency.com/feed/?taxonomy=best-regions&post_type=best&best-regions=north-america",
    },
    {
        "label": "The Hill",
        "topic": "US News",
        "feed_url": "https://thehill.com/feed/",
    },

    # ── Hip Hop ──────────────────────────────────────────
    {
        "label": "XXL Magazine",
        "topic": "Hip Hop",
        "feed_url": "https://www.xxlmag.com/feed/",
    },
    {
        "label": "Rap-Up",
        "topic": "Hip Hop",
        "feed_url": "https://www.rap-up.com/feed/",
    },
    {
        "label": "The Source",
        "topic": "Hip Hop",
        "feed_url": "https://thesource.com/feed/",
    },

    # ── Gaming ───────────────────────────────────────────
    {
        "label": "IGN",
        "topic": "Gaming",
        "feed_url": "https://feeds.feedburner.com/ign/all",
    },
    {
        "label": "PC Gamer",
        "topic": "Gaming",
        "feed_url": "https://www.pcgamer.com/rss/",
    },
    {
        "label": "Game Informer",
        "topic": "Gaming",
        "feed_url": "https://www.gameinformer.com/rss.xml",
    },
]
