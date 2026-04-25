"""Memory service — per-user semantic facts with embeddings. Owns memories table."""
import json
import time
import uuid
import struct
from pathlib import Path

from src.core.db import _connect


class MemoryService:
    """Per-user memory with embedding-based semantic search via nomic-embed-text."""

    _EMBED_MODEL = "nomic-embed-text"

    def _embed(self, text: str) -> list[float]:
        import ollama

        resp = ollama.embeddings(model=self._EMBED_MODEL, prompt=text)
        return resp["embedding"]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot / (norm_a * norm_b + 1e-8)

    def remember(self, fact: str, user_id: str) -> str:
        """Store a memory with its embedding. Returns memory_id."""
        memory_id = str(uuid.uuid4())
        now = time.time()
        embedding = self._embed(fact)
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        conn = _connect()
        conn.execute(
            "INSERT INTO memories (memory_id, user_id, content, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, user_id, fact, blob, now),
        )
        conn.commit()
        conn.close()
        return memory_id

    def recall(self, query: str, user_id: str, top_k: int = 5) -> list[dict]:
        """Semantic search over user memories. Returns top-k matches with scores."""
        query_vec = self._embed(query)
        conn = _connect()
        rows = conn.execute(
            "SELECT memory_id, content, embedding, created_at FROM memories WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        conn.close()

        scored = []
        for row in rows:
            memory_id, content, blob, created_at = row
            vec = struct.unpack(f"{len(blob) // 4}f", blob)
            score = self._cosine(query_vec, list(vec))
            scored.append((score, memory_id, content, created_at))

        scored.sort(reverse=True)
        return [
            {
                "memory_id": mid,
                "content": content,
                "score": round(score, 4),
                "created_at": created_at,
            }
            for score, mid, content, created_at in scored[:top_k]
        ]

    def list_memories(self, user_id: str) -> list[dict]:
        """List all memories for a user, newest first."""
        conn = _connect()
        rows = conn.execute(
            "SELECT memory_id, content, created_at FROM memories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        conn.close()
        return [
            {"memory_id": r[0], "content": r[1], "created_at": r[2]} for r in rows
        ]

    def forget(self, memory_id: str, user_id: str) -> bool:
        """Delete a specific memory. Returns True if deleted."""
        conn = _connect()
        cur = conn.execute(
            "DELETE FROM memories WHERE memory_id = ? AND user_id = ?",
            (memory_id, user_id),
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0


# Legacy flat-file note helpers (agent-scoped, no user_id) — kept for compat
MEMORY_DIR = Path(__file__).parent.parent / "memory"


def _file(agent: str) -> Path:
    MEMORY_DIR.mkdir(exist_ok=True)
    return MEMORY_DIR / f"{agent}.json"


def _load_file(agent: str) -> list[str]:
    f = _file(agent)
    return json.loads(f.read_text()) if f.exists() else []


def load_memory(agent: str = "shared") -> list[str]:
    """Legacy: load memory for an agent (disk-based)."""
    shared = _load_file("shared")
    if agent == "shared":
        return shared
    return shared + _load_file(agent)


_agents_memory: dict[str, list[str]] = {}


def note(fact: str, agent: str = "shared") -> None:
    """Legacy: save a note to an agent's memory (disk file, no embeddings)."""
    if agent not in _agents_memory:
        _agents_memory[agent] = _load_file(agent)
    _agents_memory[agent].append(fact)
    _file(agent).write_text(json.dumps(_agents_memory[agent], indent=2))


# Module-level instance for gateway use
_service = MemoryService()


def remember(fact: str, user_id: str) -> str:
    return _service.remember(fact, user_id)


def recall(query: str, user_id: str, top_k: int = 5) -> list[dict]:
    return _service.recall(query, user_id, top_k=top_k)


def list_memories(user_id: str) -> list[dict]:
    return _service.list_memories(user_id)


def forget(memory_id: str, user_id: str) -> bool:
    return _service.forget(memory_id, user_id)