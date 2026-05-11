"""LLM adapter abstraction.

Swap the active provider by changing `default_adapter` or setting LLM_PROVIDER
in the environment. All agent and executor code calls the adapter, never the
provider SDK directly.

Adding a new provider:
  1. Subclass LLMAdapter and implement complete().
  2. Register it in _ADAPTERS below.
  3. Set LLM_PROVIDER=<name> in the environment.
"""
import os
from abc import ABC, abstractmethod

import ollama

from config import DEFAULT_MODEL


class LLMAdapter(ABC):
    """Minimal interface for structured-output LLM calls.

    complete() sends a message list and an output JSON schema, and returns
    a JSON string that conforms to that schema. The caller is responsible
    for parsing it.
    """

    @abstractmethod
    def complete(self, messages: list[dict], schema: dict, model: str) -> str: ...

    def log_usage(self, response: dict) -> None:
        prompt = response.get("prompt_eval_count", 0)
        generated = response.get("eval_count", 0)
        if prompt:
            print(f"[ctx] prompt={prompt} generated={generated}", flush=True)


class OllamaAdapter(LLMAdapter):
    def complete(self, messages: list[dict], schema: dict, model: str) -> str:
        response = ollama.chat(
            model=model,
            messages=messages,
            format=schema,
            options={"temperature": 0, "think": False},
        )
        self.log_usage(response)
        return response["message"]["content"]


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
