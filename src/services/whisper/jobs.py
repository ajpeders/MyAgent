"""Async voice-agent job store + ntfy push notifier."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

import httpx

from src.core.db import _connect


log = logging.getLogger(__name__)


STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class JobStore:
    def create(self, user_id: str, source: str) -> dict:
        job_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute(
            "INSERT INTO voice_jobs (job_id, user_id, status, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, user_id, STATUS_PENDING, source, now),
        )
        conn.commit()
        conn.close()
        return {"job_id": job_id, "user_id": user_id, "status": STATUS_PENDING, "source": source, "created_at": now}

    def mark_running(self, job_id: str) -> None:
        conn = _connect()
        conn.execute("UPDATE voice_jobs SET status = ? WHERE job_id = ?", (STATUS_RUNNING, job_id))
        conn.commit()
        conn.close()

    def complete(self, job_id: str, result: dict) -> None:
        conn = _connect()
        conn.execute(
            "UPDATE voice_jobs SET status=?, transcript=?, tool=?, args_json=?, result_json=?, reply=?, error=?, completed_at=? WHERE job_id=?",
            (
                STATUS_DONE,
                result.get("transcript"),
                result.get("tool"),
                json.dumps(result.get("args") or {}),
                json.dumps(result.get("result")),
                result.get("reply"),
                result.get("error"),
                time.time(),
                job_id,
            ),
        )
        conn.commit()
        conn.close()

    def fail(self, job_id: str, error: str) -> None:
        conn = _connect()
        conn.execute(
            "UPDATE voice_jobs SET status=?, error=?, completed_at=? WHERE job_id=?",
            (STATUS_FAILED, error, time.time(), job_id),
        )
        conn.commit()
        conn.close()

    def get(self, user_id: str, job_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT job_id, user_id, status, source, transcript, tool, args_json, result_json, reply, error, created_at, completed_at "
            "FROM voice_jobs WHERE user_id = ? AND job_id = ?",
            (user_id, job_id),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "job_id": row[0],
            "user_id": row[1],
            "status": row[2],
            "source": row[3],
            "transcript": row[4],
            "tool": row[5],
            "args": json.loads(row[6]) if row[6] else {},
            "result": json.loads(row[7]) if row[7] else None,
            "reply": row[8],
            "error": row[9],
            "created_at": row[10],
            "completed_at": row[11],
        }


class NtfyNotifier:
    """POSTs reply text to an ntfy topic. No-op if no topic configured."""

    def __init__(self, topic: str | None, base_url: str = "https://ntfy.sh", auth: str | None = None):
        self.topic = (topic or "").strip()
        self.base_url = base_url.rstrip("/")
        self.auth = (auth or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.topic)

    async def publish(self, message: str, *, title: str | None = None, tags: list[str] | None = None) -> None:
        if not self.enabled or not message:
            return
        url = f"{self.base_url}/{self.topic}"
        headers = {}
        if title:
            headers["Title"] = title
        if tags:
            headers["Tags"] = ",".join(tags)
        if self.auth:
            headers["Authorization"] = self.auth
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=message.encode("utf-8"), headers=headers)
                resp.raise_for_status()
        except Exception as exc:
            log.warning("ntfy publish failed for topic=%s: %s", self.topic, exc)
