import json
from pathlib import Path

MEMORY_DIR = Path(__file__).parent / "memory"


def _file(agent: str) -> Path:
    MEMORY_DIR.mkdir(exist_ok=True)
    return MEMORY_DIR / f"{agent}.json"


def _load_file(agent: str) -> list[str]:
    f = _file(agent)
    return json.loads(f.read_text()) if f.exists() else []


def load_memory(agent: str = "shared") -> list[str]:
    """Load memory for an agent. Non-shared agents also inherit shared facts."""
    shared = _load_file("shared")
    if agent == "shared":
        return shared
    return shared + _load_file(agent)


def save_memory(facts: list[str], agent: str = "shared") -> None:
    _file(agent).write_text(json.dumps(facts, indent=2))


def remember(fact: str, agent: str = "shared") -> None:
    own = _load_file(agent)
    own.append(fact)
    save_memory(own, agent)
