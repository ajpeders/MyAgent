"""Standardised system prompt builder.

All agents call build_system_prompt() so every agent prompt has the same
structure and is easy to read, diff, and port to other providers.

Output format:
  You are {role}.

  ## Tools
  - tool_name: description
    - `param` (type) [required]: description

  ## {Context section}
  - item

  ## Memory
  - fact
"""
from .defs import ToolDef


def build_system_prompt(
    role: str,
    tools: list[ToolDef],
    memory: list[str] | None = None,
    context: dict[str, list[str]] | None = None,
) -> str:
    """
    Args:
        role:    One-sentence description of what this agent does.
        tools:   Ordered list of tools available to this agent.
        memory:  Facts from previous sessions (injected fresh each time).
        context: Extra named sections, e.g. {"Available mailboxes": ["Inbox", ...]}.
    """
    lines: list[str] = [f"You are {role}.", "", "## Tools"]

    for tool in tools:
        lines.append(f"- **{tool.name}**: {tool.description}")
        for p in tool.params:
            req = " *(required)*" if p.required else ""
            lines.append(f"  - `{p.name}` ({p.type}){req}: {p.description}")

    if context:
        for section, items in context.items():
            lines += ["", f"## {section}"]
            lines += [f"- {item}" for item in items] if items else ["- (none)"]

    lines += ["", "## Memory"]
    lines += [f"- {m}" for m in memory] if memory else ["- None yet."]

    return "\n".join(lines)
