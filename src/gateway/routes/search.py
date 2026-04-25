"""Search routes — /api/search/*."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.search.service import SearchService, SearchServiceError, ProviderTimeoutError, BrowseError


router = APIRouter()
_search_service = SearchService()


class SearchRequest(BaseModel):
    query: str


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
def api_search(req: SearchRequest):
    try:
        result = _search_service.search(req.query)
    except ProviderTimeoutError:
        raise HTTPException(status_code=504, detail="Search provider timed out")
    except SearchServiceError as e:
        raise HTTPException(status_code=502, detail=f"Search provider error: {e}")
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

    return SearchResponse(
        answer=result["answer"],
        results=[
            SearchResultResponse(title=r["title"], url=r["url"], snippet=r["snippet"])
            for r in result["results"]
        ],
    )


@router.get("/api/search/browse", response_model=BrowseResponse)
def api_browse(url: str):
    try:
        result = _search_service.browse(url)
    except ProviderTimeoutError:
        raise HTTPException(status_code=504, detail="Fetch timed out")
    except BrowseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

    return BrowseResponse(
        summary=result["summary"],
        url=result["url"],
        title=result.get("title"),
    )