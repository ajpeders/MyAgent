"""LLM adapters — pluggable provider abstraction.

Swap the active provider by changing `default_adapter` or setting LLM_PROVIDER
in the environment. All agent and executor code calls the adapter, never the
provider SDK directly.

Adding a new provider:
  1. Subclass LLMAdapter and implement complete() and stream_complete().
  2. Register it in _ADAPTERS below.
  3. Set LLM_PROVIDER=<name> in the environment.
"""
import asyncio
import os
from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMAdapter(ABC):
    """Minimal interface for structured-output LLM calls.

    complete() sends a message list and an output JSON schema, and returns
    a JSON string that conforms to that schema. The caller is responsible
    for parsing it.

    stream_complete() yields tokens as they arrive — use for SSE streaming.
    """

    @abstractmethod
    async def complete(self, messages: list[dict], schema: dict, model: str) -> str: ...

    def complete_sync(self, messages: list[dict], schema: dict, model: str) -> str:
        """Synchronous wrapper — use in sync code paths."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.complete(messages, schema, model)).result()
        return asyncio.run(self.complete(messages, schema, model))

    @abstractmethod
    async def stream_complete(self, messages: list[dict], schema: dict, model: str) -> AsyncIterator[str]: ...

    def log_usage(self, response: dict) -> None:
        prompt = response.get("prompt_eval_count", 0)
        generated = response.get("eval_count", 0)
        if prompt:
            print(f"[ctx] prompt={prompt} generated={generated}", flush=True)


class OllamaAdapter(LLMAdapter):
    async def complete(self, messages: list[dict], schema: dict, model: str) -> str:
        import ollama

        def _call():
            return ollama.chat(
                model=model,
                messages=messages,
                format=schema,
                options={"temperature": 0, "think": False, "num_predict": 4096},
            )

        response = await asyncio.to_thread(_call)
        self.log_usage(response)
        return response["message"]["content"]

    async def stream_complete(self, messages: list[dict], schema: dict, model: str) -> AsyncIterator[str]:
        import ollama

        def _call():
            return ollama.chat(
                model=model,
                messages=messages,
                format=schema,
                options={"temperature": 0, "think": False, "num_predict": 4096},
                stream=True,
            )

        response = await asyncio.to_thread(_call)
        accumulated = ""
        async for chunk in self._async_stream(response):
            token = chunk["message"]["content"]
            accumulated += token
            yield token
        self.log_usage({"message": {"content": accumulated}})

    async def _async_stream(self, sync_stream):
        for chunk in sync_stream:
            yield chunk


# ── Registry ──────────────────────────────────────────────────────────────────

_ADAPTERS: dict[str, type[LLMAdapter]] = {
    "ollama": OllamaAdapter,
    # "claude":  ClaudeAdapter,   # add when needed
    # "openai":  OpenAIAdapter,   # add when needed
}

_provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
if _provider not in _ADAPTERS:
    raise ValueError(f"Unknown LLM_PROVIDER={_provider!r}. Choose from: {list(_ADAPTERS)}")

default_adapter: LLMAdapter = _ADAPTERS[_provider]()