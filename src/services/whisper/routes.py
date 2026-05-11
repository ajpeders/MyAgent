"""Whisper routes — transcribe, list, delete. Accepts JWT or device token."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.config import NTFY_AUTH, NTFY_BASE_URL, NTFY_TOPIC
from src.gateway.middleware import jwt_required, require_user

from .agent import VoiceAgentService
from .jobs import JobStore, NtfyNotifier

log = logging.getLogger(__name__)
from .errors import (
    PayloadTooLargeError,
    TranscriptionError,
    TranscriptNotFoundError,
    WhisperConfigError,
    WhisperError,
)
from .models import HistoryEntry, HistoryListResponse, TranscriptionResponse
from .service import WhisperService
from .store import WhisperStore


MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB


def get_whisper_service() -> WhisperService:
    """Dependency injection — override in tests."""
    return WhisperService()


def get_whisper_store() -> WhisperStore:
    return WhisperStore()


def get_voice_agent() -> VoiceAgentService:
    return VoiceAgentService()


def get_job_store() -> JobStore:
    return JobStore()


def get_notifier() -> NtfyNotifier:
    return NtfyNotifier(NTFY_TOPIC, base_url=NTFY_BASE_URL, auth=NTFY_AUTH)


router = APIRouter()


def _detect_source(request: Request) -> str:
    """Web requests carry JWT; Shortcuts carry X-Device-Token."""
    if request.headers.get("X-Device-Token"):
        return "shortcut"
    return "web"


@router.post("/api/whisper/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    request: Request,
    filename: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
    whisper: WhisperService = Depends(get_whisper_service),
    store: WhisperStore = Depends(get_whisper_store),
) -> TranscriptionResponse:
    user_id = require_user(request)
    audio_bytes = await request.body()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio payload exceeds {MAX_AUDIO_BYTES} bytes",
        )
    source = _detect_source(request)
    try:
        result = await whisper.transcribe(
            audio_bytes,
            filename=filename,
            language=language,
            prompt=prompt,
        )
        saved = store.save(user_id, source, result)
        return TranscriptionResponse(**saved)
    except WhisperConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WhisperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected transcription error: {exc}") from exc


@router.post("/api/whisper/agent")
async def voice_agent(
    request: Request,
    filename: str | None = None,
    agent: VoiceAgentService = Depends(get_voice_agent),
):
    user_id = require_user(request)
    audio_bytes = await request.body()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio payload exceeds {MAX_AUDIO_BYTES} bytes",
        )
    source = _detect_source(request)
    try:
        return await agent.handle(audio_bytes, user_id, source=source, filename=filename)
    except WhisperConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice agent error: {exc}") from exc


async def _run_async_job(
    audio_bytes: bytes,
    user_id: str,
    source: str,
    filename: str | None,
    job_id: str,
    agent: VoiceAgentService,
    store: JobStore,
    notifier: NtfyNotifier,
) -> None:
    store.mark_running(job_id)
    try:
        result = await agent.handle(audio_bytes, user_id, source=source, filename=filename)
        store.complete(job_id, result)
        reply = result.get("reply") or ""
        if reply:
            tool = result.get("tool") or "voice"
            await notifier.publish(reply, title=f"Voice · {tool}", tags=["microphone"])
    except Exception as exc:
        log.exception("voice-agent async job=%s failed", job_id)
        store.fail(job_id, str(exc))
        await notifier.publish(f"Voice agent failed: {exc}", title="Voice · error", tags=["warning"])


@router.post("/api/whisper/agent/async", status_code=202)
async def voice_agent_async(
    request: Request,
    filename: str | None = None,
    agent: VoiceAgentService = Depends(get_voice_agent),
    store: JobStore = Depends(get_job_store),
    notifier: NtfyNotifier = Depends(get_notifier),
):
    user_id = require_user(request)
    audio_bytes = await request.body()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio payload exceeds {MAX_AUDIO_BYTES} bytes",
        )
    source = _detect_source(request)
    job = store.create(user_id, source)
    asyncio.create_task(
        _run_async_job(audio_bytes, user_id, source, filename, job["job_id"], agent, store, notifier)
    )
    return {"job_id": job["job_id"], "status": "pending", "push_enabled": notifier.enabled}


@router.get("/api/whisper/jobs/{job_id}")
async def get_voice_job(
    request: Request,
    job_id: str,
    store: JobStore = Depends(get_job_store),
):
    user_id = require_user(request)
    job = store.get(user_id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/api/whisper/transcripts", response_model=HistoryListResponse)
async def list_transcripts(
    request: Request,
    limit: int = 50,
    store: WhisperStore = Depends(get_whisper_store),
) -> HistoryListResponse:
    payload = jwt_required(request)
    rows = store.list_for_user(payload["user_id"], limit=limit)
    return HistoryListResponse(transcripts=[HistoryEntry(**row) for row in rows])


@router.delete("/api/whisper/transcripts/{transcript_id}")
async def delete_transcript(
    request: Request,
    transcript_id: str,
    store: WhisperStore = Depends(get_whisper_store),
):
    payload = jwt_required(request)
    deleted = store.delete(payload["user_id"], transcript_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return {"deleted": True}
