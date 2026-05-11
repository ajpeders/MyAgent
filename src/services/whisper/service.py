"""Whisper transcription service."""
from __future__ import annotations

import asyncio
import os
import tempfile
from functools import lru_cache
from typing import Any

from src.core.config import (
    WHISPER_BEAM_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)

from .errors import TranscriptionError, WhisperConfigError


def _normalize_device(device: str) -> str:
    return "cuda" if device == "auto" else device


def _normalize_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise WhisperConfigError(
            "Whisper dependency is not installed. Add `faster-whisper` to the environment."
        ) from exc

    actual_device = _normalize_device(device)
    actual_compute_type = _normalize_compute_type(compute_type, actual_device)

    try:
        return WhisperModel(model_name, device=actual_device, compute_type=actual_compute_type)
    except Exception as exc:
        raise WhisperConfigError(
            f"Failed to load Whisper model {model_name!r} on device={actual_device} "
            f"with compute_type={actual_compute_type}: {exc}"
        ) from exc


class WhisperService:
    """Local speech-to-text via faster-whisper."""

    def __init__(
        self,
        model: str = WHISPER_MODEL,
        device: str = WHISPER_DEVICE,
        compute_type: str = WHISPER_COMPUTE_TYPE,
        beam_size: int = WHISPER_BEAM_SIZE,
    ):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        if not audio_bytes:
            raise TranscriptionError("Audio payload is empty")

        return await asyncio.to_thread(
            self._transcribe_sync,
            audio_bytes,
            filename=filename,
            language=language,
            prompt=prompt,
        )

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        *,
        filename: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        model = _load_model(self.model, self.device, self.compute_type)
        suffix = os.path.splitext(filename or "audio.wav")[1] or ".wav"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp_path = handle.name
            handle.write(audio_bytes)

        try:
            segments, info = model.transcribe(
                temp_path,
                language=language,
                initial_prompt=prompt,
                beam_size=self.beam_size,
            )
            segment_list = list(segments)
        except WhisperConfigError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Whisper transcription failed: {exc}") from exc
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        duration = getattr(info, "duration", None)

        return {
            "text": text,
            "language": getattr(info, "language", language),
            "duration_seconds": float(duration) if duration is not None else None,
            "segments": [
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": segment.text.strip(),
                }
                for segment in segment_list
            ],
            "model": self.model,
        }
