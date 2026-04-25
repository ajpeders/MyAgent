"""LLM service — adapters, service wrapper, and HTTP routes."""
from .service import LLMService, complete, embeddings, chat
from .models import (
    ChatRequest,
    ChatResponse,
    CompleteRequest,
    CompleteResponse,
    EmbeddingsRequest,
    EmbeddingsResponse,
    ToolCall,
    ToolResult,
    Step,
    Plan,
)
from .errors import LLMError, ProviderError, TimeoutError

__all__ = [
    "LLMService",
    "complete",
    "embeddings",
    "chat",
    "ChatRequest",
    "ChatResponse",
    "CompleteRequest",
    "CompleteResponse",
    "EmbeddingsRequest",
    "EmbeddingsResponse",
    "ToolCall",
    "ToolResult",
    "Step",
    "Plan",
    "LLMError",
    "ProviderError",
    "TimeoutError",
]