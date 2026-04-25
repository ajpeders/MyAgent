"""Core data types for tool definitions.

A ToolDef is the single source of truth for a tool: its name, description,
and parameter schema. These are used to:
  - Generate agent system prompts automatically
  - Build per-agent JSON output schemas (so the LLM only sees its own tools)
  - Serve as documentation / spec when porting to other providers
"""
from dataclasses import dataclass, field
from typing import Literal

ParamType = Literal["string", "integer", "boolean"]


@dataclass
class ParamDef:
    name: str
    type: ParamType
    description: str
    required: bool = False
    default: str | int | bool | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default,
        }


@dataclass
class ToolDef:
    name: str
    description: str
    params: list[ParamDef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "params": [p.to_dict() for p in self.params],
        }
