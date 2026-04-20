"""Dynamic per-agent JSON schema builder.

Instead of every agent sharing the full Action schema (all action types),
build_plan_schema() produces a schema scoped to exactly the tools an agent
has registered. This narrows the LLM's output space and reduces hallucination
of unavailable actions.
"""
from enum import Enum
from pydantic import BaseModel, create_model

from .defs import ToolDef


def build_plan_schema(tools: list[ToolDef]) -> dict:
    """Return a JSON schema for Plan restricted to the given tools.

    The output schema is equivalent to:
        Plan(actions=[Action(type=<one of tools>, ...)])
    but with ActionType restricted to only the provided tool names.
    """
    # Build a restricted ActionType enum from the tool names
    RestrictedActionType = Enum(
        "ActionType",
        {t.name: t.name for t in tools},
        type=str,
    )

    # Action model — same fields as actions/action.py but with restricted type
    RestrictedAction = create_model(
        "Action",
        type=(RestrictedActionType, ...),
        content=(str, ""),
        count=(int, 10),
        unread_only=(bool, False),
        folder=(str, "Trash"),
        filter_from=(str, ""),
        filter_subject=(str, ""),
        account=(str, ""),
        indices=(list[int], []),
        continue_conversation=(bool, False),
    )

    RestrictedPlan = create_model(
        "Plan",
        actions=(list[RestrictedAction], []),
    )

    return RestrictedPlan.model_json_schema()
