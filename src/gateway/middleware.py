"""Gateway middleware — API key validation and session loading."""
from fastapi import Request
from fastapi.responses import JSONResponse
from core.config import API_KEY


def require_api_key(request: Request, call_next):
    """Validate X-API-Key for admin endpoints."""
    if API_KEY and request.url.path.startswith("/api/admin"):
        if request.url.path == "/api/admin/login":
            return call_next(request)
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return call_next(request)


def get_session_id(request: Request) -> str | None:
    return request.headers.get("X-Session-ID") or request.query_params.get("session_id")


def get_user_id(request: Request) -> str | None:
    return request.headers.get("X-User-ID")