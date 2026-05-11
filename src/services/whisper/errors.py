"""Whisper service error types."""
from src.services.errors import ServiceError


class WhisperError(ServiceError):
    pass


class WhisperConfigError(WhisperError):
    pass


class TranscriptionError(WhisperError):
    pass


class TranscriptNotFoundError(WhisperError):
    pass


class PayloadTooLargeError(WhisperError):
    pass
