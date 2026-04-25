"""LLM service request/response models."""
from pydantic import BaseModel


# ── Tool execution models ─────────────────────────────────────────────────────

class ToolCall(BaseModel):
    """A single tool invocation from the LLM."""
    id: str              # unique call ID, e.g. "a1", "a2"
    name: str           # tool name, e.g. "mail_read"
    params: dict = {}   # parameters passed to the tool


class ToolResult(BaseModel):
    """Result of a tool execution, fed back to the LLM."""
    id: str              # matches ToolCall.id
    success: bool
    content: str | None = None
    error: str | None = None


class Step(BaseModel):
    """One step in a plan — tools run concurrently."""
    calls: list[ToolCall]


class Plan(BaseModel):
    """A multi-step plan returned by the LLM."""
    steps: list[Step]


# ── Chat models ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Send a message to the agent with optional tool definitions."""
    messages: list[dict]   # [{"role": "system|user|assistant|tool", "content": "..."}]
    tools: list[dict] | None = None  # ToolDef list from core/tools/defs.py
    model: str = "qwen3:8b"


class ChatResponse(BaseModel):
    """Response from the agent — either text, tool calls, or both."""
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # LLM wants to call tools


# ── Legacy / direct completion ───────────────────────────────────────────────

class CompleteRequest(BaseModel):
    messages: list[dict]
    json_schema: dict = {}
    model: str = "qwen3:8b"


class CompleteResponse(BaseModel):
    content: str
    usage: dict | None = None


# ── Embeddings ────────────────────────────────────────────────────────────────

class EmbeddingsRequest(BaseModel):
    text: str
    model: str = "nomic-embed-text"


class EmbeddingsResponse(BaseModel):
    embedding: list[float]
    model: str