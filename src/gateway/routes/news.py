"""News routes — /api/news/*."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.gateway.middleware import admin_required, jwt_required
from src.services.news.errors import SourceNotFoundError
from src.services.news.curator import NewsCurator
from src.services.news.models import CreateSourceRequest, RatingRequest, UpdateSourceRequest
from src.services.news.service import NewsService
from src.services.news.store import NewsStore

router = APIRouter()
_news = NewsService()


# ── Sources ──────────────────────────────────────────────

@router.get("/api/news/sources")
async def list_sources(request: Request):
    payload = jwt_required(request)
    sources = _news.list_sources(payload["user_id"])
    return {"sources": [s.model_dump() for s in sources]}


@router.post("/api/news/sources", status_code=201)
async def create_source(request: Request, body: CreateSourceRequest):
    payload = admin_required(request)
    try:
        source = _news.create_source(
            user_id=payload["user_id"],
            label=body.label,
            topic=body.topic,
            feed_url=body.feed_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return source.model_dump()


@router.put("/api/news/sources/{source_id}")
async def update_source(request: Request, source_id: str, body: UpdateSourceRequest):
    payload = admin_required(request)
    try:
        source = _news.update_source(source_id, payload["user_id"], body.enabled)
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    return source.model_dump()


@router.delete("/api/news/sources/{source_id}")
async def delete_source(request: Request, source_id: str):
    payload = admin_required(request)
    try:
        _news.delete_source(source_id, payload["user_id"])
        return {"status": "deleted"}
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")


@router.post("/api/news/sources/seed")
async def seed_defaults(request: Request):
    payload = admin_required(request)
    added = _news.seed_defaults(payload["user_id"])
    return {"added": [s.model_dump() for s in added], "count": len(added)}


# ── Articles ─────────────────────────────────────────────

@router.get("/api/news/articles")
async def list_articles(
    request: Request,
    topic: str | None = None,
    source_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    payload = jwt_required(request)
    articles = _news.list_articles(
        payload["user_id"], topic=topic, source_id=source_id, limit=limit, offset=offset,
    )
    return {"articles": [a.model_dump() for a in articles]}


@router.post("/api/news/refresh")
async def refresh_feeds(request: Request):
    payload = jwt_required(request)
    count = _news.refresh_feeds(payload["user_id"])
    return {"new_articles": count}


# ── Curated Feed ────────────────────────────────────────

_store = NewsStore()


@router.get("/api/news/curated")
async def list_curated(request: Request, limit: int = 20, offset: int = 0):
    payload = jwt_required(request)
    articles = _store.list_curated(payload["user_id"], limit, offset)
    return {"articles": articles}


@router.post("/api/news/curate")
async def curate(request: Request):
    payload = admin_required(request)
    count = await NewsCurator().curate(payload["user_id"])
    return {"curated": count}


# ── Ratings ─────────────────────────────────────────────

@router.post("/api/news/curated/{curated_id}/rate")
async def rate_curated(request: Request, curated_id: str, body: RatingRequest):
    payload = jwt_required(request)
    _store.rate_curated(payload["user_id"], curated_id, body.rating)
    return {"status": "ok"}


@router.post("/api/news/sources/{source_id}/rate")
async def rate_source(request: Request, source_id: str, body: RatingRequest):
    payload = jwt_required(request)
    _store.rate_source(payload["user_id"], source_id, body.rating)
    return {"status": "ok"}
