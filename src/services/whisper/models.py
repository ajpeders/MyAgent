"""Whisper service request/response models."""
from pydantic import BaseModel, Field


class TranscriptionResponse(BaseModel):
    transcript_id: str | None = None
    text: str
    language: str | None = None
    duration_seconds: float | None = None
    segments: list[dict] = Field(default_factory=list)
    model: str
    source: str | None = None
    captured_at: float | None = None


class HistoryEntry(BaseModel):
    transcript_id: str
    source: str
    text: str
    language: str | None = None
    duration_seconds: float | None = None
    segments: list[dict] = Field(default_factory=list)
    model: str
    captured_at: float


class HistoryListResponse(BaseModel):
    transcripts: list[HistoryEntry]
