"""In-memory cache for user enc_keys (passwords) — needed to decrypt IMAP
credentials when authentication happens via device token (no JWT, no enc_key
in the request).

Cleared on logout or TTL expiry. Never persisted — survives only as long as the
process. Restarting the server forces re-login for mail access.
"""
from __future__ import annotations

import threading
import time


DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h


class EncKeyCache:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[str, tuple[str, float]] = {}

    def put(self, user_id: str, enc_key: str) -> None:
        if not user_id or not enc_key:
            return
        with self._lock:
            self._store[user_id] = (enc_key, time.time() + self._ttl)

    def get(self, user_id: str) -> str | None:
        with self._lock:
            entry = self._store.get(user_id)
            if not entry:
                return None
            enc_key, expires_at = entry
            if time.time() >= expires_at:
                self._store.pop(user_id, None)
                return None
            return enc_key

    def clear(self, user_id: str) -> None:
        with self._lock:
            self._store.pop(user_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._store.clear()


_default_cache: EncKeyCache | None = None


def default_cache() -> EncKeyCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = EncKeyCache()
    return _default_cache
