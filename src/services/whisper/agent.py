"""Voice agent — single-shot: transcribe → LLM picks one tool → execute → reply.

Stateless. No multi-turn loop. Returns a structured response the phone can speak.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from src.core.config import DEFAULT_MODEL
from src.services.calendar.service import CalendarService
from src.services.llm.service import LLMService
from src.services.memory.service import MemoryService
from src.services.search.service import SearchService
from src.services.whisper.service import WhisperService
from src.services.whisper.store import WhisperStore


log = logging.getLogger(__name__)


TOOLS = ["save_note", "recall_notes", "create_event", "list_events", "search_web", "answer"]


AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string", "enum": TOOLS},
        "args": {"type": "object"},
        "reply": {"type": "string"},
    },
    "required": ["tool", "reply"],
}


SYSTEM_PROMPT_TEMPLATE = """\
You are a personal voice assistant. The user just spoke one short command. Pick ONE tool to handle it, fill its args, and write a brief natural-language reply confirming what you did (or answering directly if no tool is needed).

Today is {today} ({weekday}). Current time is {now}.

Tools:
- save_note(text): store a personal note. Use for "remember X", todos, grocery items, anything to recall later.
- recall_notes(query): semantic search over saved notes. Use for "what did I say about X", "do I have notes on Y".
- create_event(title, date, time?, description?): add to calendar. date as YYYY-MM-DD, time as HH:MM (24-hour).
- list_events(start, end): get calendar events in a date range. Both as YYYY-MM-DD.
- search_web(query): web search for current facts, news, weather, etc.
- answer(text): no data tool needed — just answer directly. Use for greetings, opinions, simple Q&A from your own knowledge.

Always respond with a single JSON object: {{"tool": "<one of {tools}>", "args": {{...}}, "reply": "<spoken reply>"}}

Keep replies short (1-2 sentences) — they will be read aloud. Use natural spoken language, not lists or markdown."""


class VoiceAgentError(Exception):
    pass


class VoiceAgentService:
    def __init__(
        self,
        whisper: WhisperService | None = None,
        llm: LLMService | None = None,
        memory: MemoryService | None = None,
        calendar: CalendarService | None = None,
        search: SearchService | None = None,
        store: WhisperStore | None = None,
        model: str = DEFAULT_MODEL,
    ):
        self.whisper = whisper or WhisperService()
        self.llm = llm or LLMService()
        self.memory = memory or MemoryService()
        self.calendar = calendar or CalendarService()
        self.search = search or SearchService()
        self.store = store or WhisperStore()
        self.model = model

    async def handle(
        self,
        audio_bytes: bytes,
        user_id: str,
        *,
        source: str = "shortcut",
        filename: str | None = None,
    ) -> dict[str, Any]:
        transcription = await self.whisper.transcribe(audio_bytes, filename=filename)
        text = (transcription.get("text") or "").strip()
        saved = self.store.save(user_id, source, transcription)

        if not text:
            return _empty_response(saved, "I didn't catch that — try again.")

        plan = await self._plan(text)
        tool = plan.get("tool") or "answer"
        args = plan.get("args") or {}
        reply = (plan.get("reply") or "").strip() or "Okay."

        result: Any = None
        action_error: str | None = None
        try:
            result = self._dispatch(tool, args, user_id)
        except Exception as exc:
            log.exception("voice-agent tool=%s failed", tool)
            action_error = str(exc)
            if not reply:
                reply = f"Sorry — that didn't work: {exc}"

        return {
            "transcript_id": saved["transcript_id"],
            "transcript": text,
            "tool": tool,
            "args": args,
            "result": result,
            "reply": reply,
            "error": action_error,
            "captured_at": saved["captured_at"],
        }

    async def _plan(self, text: str) -> dict[str, Any]:
        now = datetime.now()
        system = SYSTEM_PROMPT_TEMPLATE.format(
            today=now.strftime("%Y-%m-%d"),
            weekday=now.strftime("%A"),
            now=now.strftime("%H:%M"),
            tools=", ".join(TOOLS),
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        raw = await self.llm.complete(messages, AGENT_SCHEMA, self.model)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("voice-agent LLM returned non-JSON: %r", raw)
            return {"tool": "answer", "args": {}, "reply": raw[:400] or "Sorry, I couldn't parse that."}

    def _dispatch(self, tool: str, args: dict, user_id: str) -> Any:
        if tool == "save_note":
            text = _require_str(args, "text")
            memory_id = self.memory.remember(text, user_id)
            return {"memory_id": memory_id}

        if tool == "recall_notes":
            query = _require_str(args, "query")
            top_k = int(args.get("top_k") or 5)
            return self.memory.recall(query, user_id, top_k=top_k)

        if tool == "create_event":
            title = _require_str(args, "title")
            date = _require_str(args, "date")
            event = self.calendar.create_event(
                user_id=user_id,
                title=title,
                date=date,
                time=args.get("time") or None,
                description=args.get("description") or None,
            )
            return event.model_dump() if hasattr(event, "model_dump") else dict(event)

        if tool == "list_events":
            start = _require_str(args, "start")
            end = _require_str(args, "end")
            events = self.calendar.get_events(user_id, start, end)
            return [e.model_dump() if hasattr(e, "model_dump") else dict(e) for e in events]

        if tool == "search_web":
            query = _require_str(args, "query")
            return self.search.search(query)

        if tool == "answer":
            return None

        raise VoiceAgentError(f"Unknown tool: {tool!r}")


def _require_str(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VoiceAgentError(f"Missing required arg: {key}")
    return value.strip()


def _empty_response(saved: dict, reply: str) -> dict[str, Any]:
    return {
        "transcript_id": saved["transcript_id"],
        "transcript": "",
        "tool": "answer",
        "args": {},
        "result": None,
        "reply": reply,
        "error": None,
        "captured_at": saved["captured_at"],
    }
