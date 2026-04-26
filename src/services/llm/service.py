"""LLM service — wraps adapters for structured completions, embeddings, and agent chat."""
import asyncio

from .adapters import default_adapter, _ADAPTERS
from .errors import ProviderError, TimeoutError


_EMBED_MODEL = "nomic-embed-text"


class LLMService:
    """LLM completion and embeddings via pluggable adapters."""

    def __init__(self, provider: str = "ollama"):
        if provider.lower() not in _ADAPTERS:
            raise ValueError(f"Unknown LLM provider={provider!r}. Choose from: {list(_ADAPTERS)}")
        self._adapter = _ADAPTERS[provider.lower()]()

    async def complete(self, messages: list[dict], schema: dict, model: str) -> str:
        """Send a message list and JSON schema, return the response content string."""
        try:
            return await self._adapter.complete(messages, schema, model)
        except TimeoutError as e:
            raise TimeoutError(f"LLM provider timed out: {e}") from e
        except Exception as e:
            raise ProviderError(f"LLM provider error: {e}") from e

    async def embeddings(self, text: str, model: str = _EMBED_MODEL) -> list[float]:
        """Generate an embedding vector for the given text."""
        import ollama

        def _call():
            return ollama.embeddings(model=model, prompt=text)

        try:
            resp = await asyncio.to_thread(_call)
            return resp["embedding"]
        except Exception as e:
            raise ProviderError(f"Embeddings provider error: {e}") from e

    async def stream_complete(self, messages: list[dict], schema: dict, model: str):
        """Stream tokens as they arrive. Returns an async iterable of strings."""
        try:
            return self._adapter.stream_complete(messages, schema, model)
        except TimeoutError as e:
            raise TimeoutError(f"LLM provider timed out: {e}") from e
        except Exception as e:
            raise ProviderError(f"LLM provider error: {e}") from e

    async def chat(self, messages: list[dict], tools: list[dict] | None, model: str) -> dict:
        """Agent-style chat with optional tool definitions.

        If tools are provided, builds a system prompt with tool descriptions
        and uses a tool-calling JSON schema. Returns either content or tool_calls.

        Tool schema format expected:
            [{"name": "...", "description": "...", "params": [...]}]
        """
        if tools:
            system_msg, schema = _build_tool_prompt_and_schema(tools)
            messages = [system_msg, *messages]
        else:
            schema = {}

        content = await self.complete(messages, schema, model)

        # Try to parse as tool_calls. If it looks like JSON with "steps", it's a plan.
        # Otherwise treat as plain content.
        if _looks_like_plan(content):
            return {"tool_calls": content}
        else:
            return {"content": content}


def _build_tool_prompt_and_schema(tools: list[dict]) -> tuple[dict, dict]:
    """Build system prompt with tools and the output JSON schema for plan output."""
    tool_lines = []
    for t in tools:
        tool_lines.append(f"- **{t['name']}**: {t['description']}")
        for p in t.get("params", []):
            req = " *(required)*" if p.get("required") else ""
            tool_lines.append(f"  - `{p['name']}` ({p['type']}){req}: {p['description']}")

    system_content = (
        "You are an agent that plans and executes tasks.\n\n"
        "## Tools\n" + "\n".join(tool_lines) + "\n\n"
        "Always respond with a valid JSON object. "
        "If calling tools, respond with a Plan object:\n"
        '{"steps": [{"calls": [{"id": "a1", "name": "...", "params": {...}}]}]}\n\n'
        "If responding directly to the user, respond with:\n"
        '{"content": "your response text"}'
    )

    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "calls": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "params": {"type": "object"},
                                },
                                "required": ["id", "name", "params"],
                            },
                        }
                    },
                    "required": ["calls"],
                },
            },
            "content": {"type": "string"},
        },
        "oneOf": [
            {"required": ["steps"]},
            {"required": ["content"]},
        ],
    }

    return {"role": "system", "content": system_content}, schema


def _looks_like_plan(content: str) -> bool:
    """Heuristic: does this look like a plan JSON with steps?"""
    stripped = content.strip()
    return stripped.startswith("{") and '"steps"' in stripped


# Module-level singleton for convenience
_service = LLMService()


async def complete(messages: list[dict], schema: dict, model: str) -> str:
    return await _service.complete(messages, schema, model)


async def embeddings(text: str, model: str = _EMBED_MODEL) -> list[float]:
    return await _service.embeddings(text, model)


async def chat(messages: list[dict], tools: list[dict] | None, model: str) -> dict:
    return await _service.chat(messages, tools, model)