"""Gateway middleware — API key validation and session loading."""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from src.core.config import API_KEY
from src.core.jwt import decode


def require_api_key(request: Request, call_next):
    """Validate X-API-Key for admin endpoints."""
    if API_KEY and request.url.path.startswith("/api/admin"):
        if request.url.path == "/api/admin/login":
            return call_next(request)
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return call_next(request)


def get_token(request: Request) -> str | None:
    """Extract JWT from Authorization: Bearer header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def jwt_required(request: Request) -> dict:
    """Validate JWT and return payload. Raises HTTPException if missing or invalid."""
    token = get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    try:
        return decode(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def admin_required(request: Request) -> dict:
    """Validate JWT and require is_admin=True. Raises HTTPException otherwise."""
    payload = jwt_required(request)
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


def get_user_id(request: Request) -> str | None:
    return request.headers.get("X-User-ID")


def get_session_id(request: Request) -> str | None:
    return request.headers.get("X-Session-ID") or request.query_params.get("session_id")