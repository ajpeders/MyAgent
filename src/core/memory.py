"""Per-user memory with semantic search via embeddings.

All memory operations require a user_id. Memories are stored in SQLite
with embeddings generated using nomic-embed-text via Ollama.
"""
import json as json_lib
from pathlib import Path

from core.db import MemoryStore

_store = MemoryStore()

# ── Legacy flat-file notes (agent-scoped, no user_id) ─────────────────────────

MEMORY_DIR = Path(__file__).parent / "memory"


def _file(agent: str) -> Path:
    MEMORY_DIR.mkdir(exist_ok=True)
    return MEMORY_DIR / f"{agent}.json"


def _load_file(agent: str) -> list[str]:
    f = _file(agent)
    return json_lib.loads(f.read_text()) if f.exists() else []


def load_memory(agent: str = "shared") -> list[str]:
    """Legacy: load memory for an agent (disk-based)."""
    shared = _load_file("shared")
    if agent == "shared":
        return shared
    return shared + _load_file(agent)


def remember(fact: str, user_id: str) -> str:
    """Store a fact in the user's semantic memory. Returns memory_id."""
    return _store.add_memory(user_id, fact)


# ── Agent-scope notes (legacy, no user_id) ───────────────────────────────────

_agents_memory: dict[str, list[str]] = {}


def note(fact: str, agent: str = "shared") -> None:
    """Legacy: save a note to an agent's memory (disk file, no embeddings)."""
    if agent not in _agents_memory:
        _agents_memory[agent] = _load_file(agent)
    _agents_memory[agent].append(fact)
    _file(agent).write_text(json_lib.dumps(_agents_memory[agent], indent=2))


# ── Semantic memory ─────────────────────────────────────────────────────────

def recall(query: str, user_id: str, top_k: int = 5) -> list[dict]:
    """Semantic search over user memories. Returns top-k matches with scores."""
    return _store.search(user_id, query, top_k=top_k)


def list_memories(user_id: str) -> list[dict]:
    """List all memories for a user, newest first."""
    return _store.list_memories(user_id)


def forget(memory_id: str, user_id: str) -> bool:
    """Delete a specific memory. Returns True if deleted."""
    return _store.delete_memory(memory_id, user_id)


def recall(query: str, user_id: str, top_k: int = 5) -> list[dict]:
    """Semantic search over user memories. Returns top-k matches with scores."""
    return _store.search(user_id, query, top_k=top_k)


def list_memories(user_id: str) -> list[dict]:
    """List all memories for a user, newest first."""
    return _store.list_memories(user_id)


def forget(memory_id: str, user_id: str) -> bool:
    """Delete a specific memory. Returns True if deleted."""
    return _store.delete_memory(memory_id, user_id)
