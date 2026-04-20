"""Head agent: stateless router that classifies intent and picks a subagent."""
from core.actions.action import AgentRoute
from core.llm import default_adapter
from core.memory import load_memory
from core.tools import build_system_prompt, ToolDef, ParamDef

# The head agent's only tool is "route" — modelled as a ToolDef for consistency.
_ROUTE_TOOL = ToolDef(
    name="route",
    description="Classify the user's intent and select the right specialist agent.",
    params=[
        ParamDef("agent",  "string", 'The agent to route to: "mail", "command", or "answer".', required=True),
        ParamDef("intent", "string", "One-line summary of what the user wants.",                required=True),
    ],
)

_AGENT_CONTEXT = {
    "Available agents": [
        "mail    — read, move, save, search, or summarize emails",
        "command — run shell commands or system operations in a sandbox",
        "answer  — general questions, notes, memory, everything else",
    ]
}


class HeadAgent:
    def route(self, user_input: str, model: str) -> AgentRoute:
        system = build_system_prompt(
            role="a routing agent that classifies requests and delegates to the right specialist",
            tools=[_ROUTE_TOOL],
            memory=load_memory(),
            context=_AGENT_CONTEXT,
        )
        content = default_adapter.complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_input},
            ],
            schema=AgentRoute.model_json_schema(),
            model=model,
        )
        return AgentRoute.model_validate_json(content)
