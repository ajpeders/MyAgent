"""Agent executor — async LLM loop with tool execution.

Flow:
  User prompt → LLM → tool_calls → execute → results → LLM → content
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any

from src.services.llm.models import ToolCall, ToolResult, Plan
from src.services.llm.service import LLMService


# ── Tool context ─────────────────────────────────────────────────────────────

@dataclass
class ToolContext:
    """Session-scoped context passed to every tool function."""
    session_id: str = "_stateless"
    user_id: str = ""
    mail_engine: dict | None = None
    imap_accounts: list[dict] | None = None


# ── Result formatting ────────────────────────────────────────────────────────

def _fmt_email_list(result: dict) -> str:
    emails = result.get("emails", [])
    if not emails:
        return "(no emails)"
    lines = []
    for i, e in enumerate(emails[:20], 1):
        lines.append(f"{i}. {e.get('from', '')} | {e.get('subject', '')}")
    total = result.get("total_emails", 0)
    if total > 20:
        lines.append(f"... and {total - 20} more")
    return "\n".join(lines)


# ── Tool implementations ─────────────────────────────────────────────────────

async def _tool_mail_read(params: dict, ctx: ToolContext) -> str:
    from src.core.mail_engine import MailEngine
    from src.core.config import MAIL_SUMMARY_COUNT

    engine = (
        MailEngine.from_dict(ctx.mail_engine, imap_accounts=ctx.imap_accounts)
        if ctx.mail_engine
        else MailEngine(model="", imap_accounts=ctx.imap_accounts)
    )
    engine.fetch(
        count=params.get("count", MAIL_SUMMARY_COUNT),
        unread_only=params.get("unread_only", False),
        account=params.get("account", ""),
    )
    ctx.mail_engine = engine.to_dict()
    return _fmt_email_list(engine._mail_list_result())


async def _tool_mail_move(params: dict, ctx: ToolContext) -> str:
    from src.core.mail_engine import MailEngine
    from src.core.actions.action import Action, ActionType

    if not ctx.mail_engine:
        return "Error: no active mail session. Call mail_read first."
    engine = MailEngine.from_dict(ctx.mail_engine, imap_accounts=ctx.imap_accounts)
    action = Action(
        type=ActionType.mail_move,
        indices=params.get("indices", []),
        folder=params.get("folder", "Trash"),
    )
    msg = engine.execute(action)
    ctx.mail_engine = engine.to_dict()
    return msg


async def _tool_web_search(params: dict, ctx: ToolContext) -> str:
    from src.core.search import search_web

    result = search_web(params.get("content", ""))
    answer = result.get("answer", "")
    if result.get("results"):
        answer += "\n\nResults:\n" + "\n".join(
            f"- {r['title']}: {r['url']}" for r in result["results"][:5]
        )
    return answer


async def _tool_remember(params: dict, ctx: ToolContext) -> str:
    from src.core.memory import remember

    remember(params.get("content", ""), ctx.user_id)
    return f"Saved: {params.get('content', '')}"


async def _tool_note(params: dict, ctx: ToolContext) -> str:
    from src.core.memory import note as mem_note

    mem_note(f"[note] {params.get('content', '')}")
    return f"Note saved: {params.get('content', '')}"


async def _tool_personal_data(params: dict, ctx: ToolContext) -> str:
    from src.core.memory import recall

    results = recall(params.get("content", ""), ctx.user_id, top_k=5)
    if not results:
        return "I don't have any memories on that topic."
    lines = [f"- {r['content']} (relevance: {round(r['score'] * 100)}%)" for r in results]
    return "Here's what I remember:\n" + "\n".join(lines)


async def _tool_command(params: dict, ctx: ToolContext) -> str:
    from src.core.docker import run_in_docker

    return run_in_docker(params.get("content", ""))


async def _tool_answer(params: dict, ctx: ToolContext) -> str:
    return params.get("content", "")


async def _tool_done(params: dict, ctx: ToolContext) -> str:
    return "[done]"


TOOL_REGISTRY: dict[str, callable] = {
    "mail_read":     _tool_mail_read,
    "mail_move":     _tool_mail_move,
    "web_search":    _tool_web_search,
    "remember":      _tool_remember,
    "note":          _tool_note,
    "personal_data": _tool_personal_data,
    "command":       _tool_command,
    "answer":        _tool_answer,
    "done":          _tool_done,
}


# ── Agent executor ───────────────────────────────────────────────────────────

class AgentExecutor:
    """Async executor: prompt → LLM → tools → results → repeat until content."""

    def __init__(
        self,
        session_state: "SessionState | None" = None,
        tools: list[dict] | None = None,
        model: str = "qwen3:8b",
    ):
        from src.gateway.session import SessionState

        state = session_state or SessionState(session_id="_stateless", user_id="")
        self._ctx = ToolContext(
            session_id=state.session_id,
            user_id=state.user_id,
            mail_engine=state.mail_engine,
            imap_accounts=state.imap_accounts,
        )
        self._tools = tools or []
        self._model = model
        self._llm = LLMService()
        self._session_state = state

    def sync_run(self, prompt: str) -> str:
        """Synchronous wrapper for backward compat."""
        import asyncio
        return asyncio.run(self.run(prompt))

    async def run(self, prompt: str) -> str:
        """Main agent loop."""
        messages = [{"role": "user", "content": prompt}]

        while True:
            response = await self._llm.chat(messages, self._tools, self._model)

            if response.get("content"):
                return response["content"]

            if response.get("tool_calls"):
                plan = _parse_plan(response["tool_calls"])
                results = await self._execute_plan(plan)
                messages.extend(_tool_results_to_messages(results))
                continue

            return "No response from LLM."

    async def _execute_plan(self, plan: Plan) -> list[ToolResult]:
        """Execute plan steps sequentially, tools within each step concurrently."""
        all_results = []
        for step in plan.steps:
            step_results = await asyncio.gather(
                *[self._execute_tool(call) for call in step.calls]
            )
            all_results.extend(step_results)
        return all_results

    async def _execute_tool(self, call: ToolCall) -> ToolResult:
        func = TOOL_REGISTRY.get(call.name)
        if not func:
            return ToolResult(id=call.id, success=False, error=f"Unknown tool: {call.name}")
        try:
            result = await func(call.params, self._ctx)
            return ToolResult(id=call.id, success=True, content=str(result))
        except Exception as e:
            return ToolResult(id=call.id, success=False, error=str(e))


def _parse_plan(tool_calls: Any) -> Plan:
    """Parse LLM tool_calls response into a Plan."""
    if isinstance(tool_calls, str):
        data = json.loads(tool_calls)
    elif isinstance(tool_calls, list):
        data = {"steps": [{"calls": tool_calls}]}
    elif isinstance(tool_calls, dict):
        data = tool_calls
    else:
        raise ValueError(f"Unexpected tool_calls type: {type(tool_calls)}")
    return Plan.model_validate(data)


def _tool_results_to_messages(results: list[ToolResult]) -> list[dict]:
    """Convert tool results to assistant+tool messages for LLM context."""
    messages = []
    for r in results:
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": r.id, "name": r.id, "params": {}}],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": r.id,
            "content": r.content if r.success else f"Error: {r.error}",
        })
    return messages


# ── Backward-compat dispatch_session ─────────────────────────────────────────

def dispatch_session(
    state: "SessionState",
    prompt: str,
    model: str,
    *,
    interactive: bool = False,
    confirm: bool = False,
) -> list[dict]:
    """Legacy sync entry point. Returns list of result dicts."""
    from src.gateway.session import SessionState
    from src.core.tools.registry import MAIL_TOOLS, ANSWER_TOOLS, COMMAND_TOOLS

    state = SessionState(
        session_id=state.session_id,
        user_id=state.user_id,
        mail_engine=state.mail_engine,
        imap_accounts=state.imap_accounts,
        pending=state.pending,
    )

    # Route to pick the right tool set
    from src.core.agents.head import HeadAgent
    head = HeadAgent()
    route = head.route(prompt, model)
    agent_name = route.agent

    tool_map = {
        "mail":    [t.to_dict() for t in MAIL_TOOLS],
        "answer":  [t.to_dict() for t in ANSWER_TOOLS],
        "command": [t.to_dict() for t in COMMAND_TOOLS],
    }
    tools = tool_map.get(agent_name, [])

    executor = AgentExecutor(session_state=state, tools=tools, model=model)
    content = executor.sync_run(prompt)
    return [{"type": "answer", "content": content, "agent": agent_name}]
