"""SQLite-backed session persistence for MyDevTeam server."""
from core.db import SessionState, SessionStore

__all__ = ["SessionState", "load_session", "save_session", "delete_session"]

_store = SessionStore()


def load_session(session_id: str, user_id: str = "") -> SessionState:
    """Load session by session_id. Returns a new SessionState if not found."""
    state = _store.get_session(session_id)
    if state:
        return state
    if not user_id:
        raise ValueError("user_id required to create a new session")
    return SessionState(session_id=session_id, user_id=user_id)


def save_session(state: SessionState) -> None:
    _store.save_session(state)


def delete_session(session_id: str) -> None:
    _store.delete_session(session_id)
