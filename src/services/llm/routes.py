"""LLM service routes — /api/llm/complete, /api/llm/embeddings, /api/llm/chat."""
from fastapi import APIRouter, Depends

from .models import (
    ChatRequest,
    ChatResponse,
    CompleteRequest,
    CompleteResponse,
    EmbeddingsRequest,
    EmbeddingsResponse,
)
from .errors import LLMError, ProviderError, TimeoutError
from .service import LLMService


def get_llm_service() -> LLMService:
    """Dependency injection — override in tests."""
    return LLMService()


router = APIRouter()


@router.post("/api/llm/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, llm: LLMService = Depends(get_llm_service)) -> ChatResponse:
    """Agent-style chat with optional tool definitions.

    Pass tools=[...] to give the LLM access to a specific set of tools.
    Returns either content (direct response) or tool_calls (LLM wants to execute tools).
    """
    try:
        result = await llm.chat(req.messages, req.tools, req.model)
        return ChatResponse(**result)
    except TimeoutError as e:
        raise e
    except ProviderError as e:
        raise e
    except LLMError as e:
        raise ProviderError(str(e)) from e
    except Exception as e:
        raise ProviderError(f"Unexpected error: {e}") from e


@router.post("/api/llm/complete", response_model=CompleteResponse)
async def complete(req: CompleteRequest, llm: LLMService = Depends(get_llm_service)) -> CompleteResponse:
    try:
        content = await llm.complete(req.messages, req.json_schema, req.model)
        return CompleteResponse(content=content)
    except TimeoutError as e:
        raise e
    except ProviderError as e:
        raise e
    except LLMError as e:
        raise ProviderError(str(e)) from e
    except Exception as e:
        raise ProviderError(f"Unexpected error: {e}") from e


@router.post("/api/llm/embeddings", response_model=EmbeddingsResponse)
async def embeddings(req: EmbeddingsRequest, llm: LLMService = Depends(get_llm_service)) -> EmbeddingsResponse:
    try:
        embedding = await llm.embeddings(req.text, req.model)
        return EmbeddingsResponse(embedding=embedding, model=req.model)
    except LLMError:
        raise
    except Exception as e:
        raise ProviderError(f"Unexpected error: {e}") from e