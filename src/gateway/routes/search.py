"""Search routes — /api/search/*."""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from src.gateway.middleware import jwt_required
from src.services.auth.errors import UserNotFoundError
from src.services.auth.service import AuthService
from src.services.search.service import SearchService, SearchServiceError, ProviderTimeoutError, BrowseError


router = APIRouter()
_search_service = SearchService()
_auth_service = AuthService()


class SearchRequest(BaseModel):
    query: str
    skip_answer: bool = False


class SearchResultResponse(BaseModel):
    title: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    answer: str
    results: list[SearchResultResponse]


class BrowseResponse(BaseModel):
    summary: str
    url: str
    title: str | None


@router.post("/api/search", response_model=SearchResponse)
def api_search(req: SearchRequest, request: Request):
    try:
        payload = jwt_required(request)
        provider_name = _auth_service.get_search_provider(payload["user_id"])
        result = _search_service.search(req.query, provider_name=provider_name, skip_answer=req.skip_answer)
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProviderTimeoutError:
        raise HTTPException(status_code=504, detail="Search provider timed out")
    except SearchServiceError as e:
        raise HTTPException(status_code=502, detail=f"Search provider error: {e}")
    except Exception:
        logger.exception("Unexpected error in search route")
        raise HTTPException(status_code=500, detail="Internal server error")

    return SearchResponse(
        answer=result["answer"],
        results=[
            SearchResultResponse(title=r["title"], url=r["url"], snippet=r["snippet"])
            for r in result["results"]
        ],
    )


@router.get("/api/search/browse", response_model=BrowseResponse)
def api_browse(url: str, request: Request):
    jwt_required(request)
    try:
        result = _search_service.browse(url)
    except ProviderTimeoutError:
        raise HTTPException(status_code=504, detail="Fetch timed out")
    except BrowseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Unexpected error in search route")
        raise HTTPException(status_code=500, detail="Internal server error")

    return BrowseResponse(
        summary=result["summary"],
        url=result["url"],
        title=result.get("title"),
    )
