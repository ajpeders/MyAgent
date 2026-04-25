"""LLM service error types."""
from src.services.errors import ServiceError


class LLMError(ServiceError):
    pass


class ProviderError(LLMError):
    pass


class TimeoutError(LLMError):
    pass
