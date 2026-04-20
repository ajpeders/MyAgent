"""SQLite-backed session persistence for MyDevTeam server."""
from core.db import SessionState, SessionStore

__all__ = ["SessionState", "load_session", "save_session", "delete_session"]

_store = SessionStore()


LOCAL_USER_ID = "local"


def load_session(session_id: str, user_id: str = "") -> SessionState:
    """Load session by session_id. Returns a new SessionState if not found.

    For CLI (local) mode, user_id defaults to "local" so no auth is needed.
    """
    state = _store.get_session(session_id)
    if state:
        return state
    return SessionState(session_id=session_id, user_id=user_id or LOCAL_USER_ID)


def save_session(state: SessionState) -> None:
    _store.save_session(state)


def delete_session(session_id: str) -> None:
    _store.delete_session(session_id)
