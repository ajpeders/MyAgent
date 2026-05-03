"""Profile service — business logic and context snapshots."""
import datetime
import logging

from src.core.config import DEFAULT_MODEL
from src.services.profile.models import ContextSnapshot, Signal
from src.services.profile.store import ProfileStore

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(self) -> None:
        self._store = ProfileStore()

    # --- Interests ---

    def get_interests(self, user_id: str) -> list[str]:
        return self._store.get_interests(user_id)

    def set_interests(self, user_id: str, interests: list[str]) -> None:
        self._store.set_interests(user_id, interests)

    # --- Signals ---

    def log_signal(self, user_id: str, signal_type: str, topic: str, source: str = "") -> None:
        self._store.log_signal(user_id, signal_type, topic, source)

    # --- Model config ---

    def get_model(self, user_id: str, task: str) -> str:
        """Return the user's preferred model for *task*, falling back to DEFAULT_MODEL."""
        config = self._store.get_model_config(user_id)
        return config.get(task, DEFAULT_MODEL)

    def get_model_config(self, user_id: str) -> dict:
        return self._store.get_model_config(user_id)

    def set_model_config(self, user_id: str, config: dict) -> None:
        self._store.set_model_config(user_id, config)

    # --- Context snapshot ---

    def context_snapshot(self, user_id: str) -> ContextSnapshot:
        """Build a full context snapshot for the user."""
        interests = self._store.get_interests(user_id)
        raw_signals = self._store.get_recent_signals(user_id)
        signals = [
            Signal(
                signal_id=s["signal_id"],
                signal_type=s["signal_type"],
                topic=s["topic"],
                source=s["source"],
                created_at=s["created_at"],
            )
            for s in raw_signals
        ]

        # Calendar: today + upcoming 3 days
        calendar_today: list[dict] = []
        calendar_upcoming: list[dict] = []
        try:
            from src.services.calendar.service import CalendarService

            cal = CalendarService()
            today = datetime.date.today()
            today_str = today.isoformat()
            end_str = (today + datetime.timedelta(days=3)).isoformat()

            today_events = cal.get_events(user_id, today_str, today_str)
            calendar_today = [e.model_dump() for e in today_events]

            upcoming_events = cal.get_events(user_id, today_str, end_str)
            calendar_upcoming = [e.model_dump() for e in upcoming_events]
        except Exception:
            logger.debug("Calendar unavailable for context snapshot", exc_info=True)

        # Memory recall using interests as query
        memories: list[str] = []
        try:
            from src.services.memory.service import recall

            if interests:
                query = ", ".join(interests)
                results = recall(query, user_id, top_k=5)
                memories = [r["content"] for r in results]
        except Exception:
            logger.debug("Memory recall unavailable for context snapshot", exc_info=True)

        return ContextSnapshot(
            user_id=user_id,
            interests=interests,
            recent_signals=signals,
            calendar_today=calendar_today,
            calendar_upcoming=calendar_upcoming,
            mail_subjects=[],
            memories=memories,
        )
