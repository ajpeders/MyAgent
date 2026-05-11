"""Persistence for whisper transcripts. Owns the whisper_transcripts table."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from src.core.db import _connect


VALID_SOURCES = {"web", "shortcut"}


class WhisperStore:
    def save(self, user_id: str, source: str, result: dict[str, Any]) -> dict:
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source {source!r}; expected one of {sorted(VALID_SOURCES)}")
        transcript_id = str(uuid.uuid4())
        captured_at = time.time()
        segments_json = json.dumps(result.get("segments") or [])
        conn = _connect()
        conn.execute(
            "INSERT INTO whisper_transcripts "
            "(transcript_id, user_id, source, text, language, duration_seconds, segments_json, model, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                transcript_id,
                user_id,
                source,
                result.get("text", ""),
                result.get("language"),
                result.get("duration_seconds"),
                segments_json,
                result.get("model", ""),
                captured_at,
            ),
        )
        conn.commit()
        conn.close()
        return {
            "transcript_id": transcript_id,
            "user_id": user_id,
            "source": source,
            "text": result.get("text", ""),
            "language": result.get("language"),
            "duration_seconds": result.get("duration_seconds"),
            "segments": result.get("segments") or [],
            "model": result.get("model", ""),
            "captured_at": captured_at,
        }

    def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        conn = _connect()
        rows = conn.execute(
            "SELECT transcript_id, source, text, language, duration_seconds, segments_json, model, captured_at "
            "FROM whisper_transcripts WHERE user_id = ? "
            "ORDER BY captured_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 500))),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(user_id, row) for row in rows]

    def get(self, user_id: str, transcript_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT transcript_id, source, text, language, duration_seconds, segments_json, model, captured_at "
            "FROM whisper_transcripts WHERE user_id = ? AND transcript_id = ?",
            (user_id, transcript_id),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_dict(user_id, row)

    def delete(self, user_id: str, transcript_id: str) -> bool:
        conn = _connect()
        cursor = conn.execute(
            "DELETE FROM whisper_transcripts WHERE user_id = ? AND transcript_id = ?",
            (user_id, transcript_id),
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    @staticmethod
    def _row_to_dict(user_id: str, row: tuple) -> dict:
        return {
            "transcript_id": row[0],
            "user_id": user_id,
            "source": row[1],
            "text": row[2],
            "language": row[3],
            "duration_seconds": row[4],
            "segments": json.loads(row[5]) if row[5] else [],
            "model": row[6],
            "captured_at": row[7],
        }
