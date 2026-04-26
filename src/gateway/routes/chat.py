"""Chat route — /api/chat and /api/chat/stream."""
import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.gateway.middleware import get_session_id, jwt_required
from src.gateway.session import load_session, save_session
from src.core.executor import dispatch_session
from src.gateway.session import SessionState
from src.services.llm.service import LLMService


router = APIRouter()


class ChatRequest(BaseModel):
    prompt: str
    model: str = "qwen3:8b"
    session_id: str | None = None
    confirm: bool = False


class ActionResponse(BaseModel):
    type: str
    content: str
    agent: str | None = None
    pending_confirm: str | None = None
    emails: list[dict] | None = None
    page: int | None = None
    total_pages: int | None = None
    total_emails: int | None = None


@router.post("/api/chat")
async def chat(request: Request):
    try:
        body = ChatRequest.model_validate_json(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    payload = jwt_required(request)
    user_id = payload["user_id"]
    session_id = get_session_id(request) or body.session_id

    try:
        if session_id and session_id != "_stateless":
            state = load_session(session_id, user_id=user_id)
            results = dispatch_session(state, body.prompt, body.model, confirm=body.confirm)
            save_session(state)
        else:
            state = SessionState(session_id="_stateless", user_id=user_id)
            results = dispatch_session(state, body.prompt, body.model, confirm=body.confirm)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent backend failed: {exc}") from exc

    return [
        ActionResponse(
            type=r["type"],
            content=r["content"],
            agent=r.get("agent"),
            pending_confirm=r.get("pending_confirm"),
            emails=r.get("emails"),
            page=r.get("page"),
            total_pages=r.get("total_pages"),
            total_emails=r.get("total_emails"),
        )
        for r in results
    ]


async def _sse_token(token: str) -> str:
    return f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"


async def _sse_event(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _sse_done() -> str:
    return f"data: {json.dumps({'type': 'done'})}\n\n"


async def _chat_stream_iterator(
    prompt: str,
    model: str,
    user_id: str,
    session_id: str | None,
    confirm: bool,
) -> AsyncIterator[str]:
    """Stream tokens as they arrive, then stream final executor results."""
    llm = LLMService()

    # Load session
    if session_id and session_id != "_stateless":
        state = load_session(session_id, user_id=user_id)
    else:
        session_id = "_stateless"
        state = SessionState(session_id=session_id, user_id=user_id)

    # If a mail session is active, fall back to non-streaming dispatch
    # (mail engine doesn't benefit from streaming)
    if state.mail_engine:
        results = dispatch_session(state, prompt, model, confirm=confirm)
        if session_id != "_stateless":
            save_session(state)
        for r in results:
            yield await _sse_event({
                "type": r["type"],
                "content": r["content"],
                "agent": r.get("agent"),
            })
        yield await _sse_done()
        return

    # Build agent routing context — route first, then stream the LLM tokens
    from src.core.agents.head import HeadAgent
    from src.core.agents import AGENTS

    head = HeadAgent()
    route = head.route(prompt, model)
    agent_name = route.agent

    if agent_name == "mail":
        # Mail agent — fetch first, then stream results
        results = [{"type": "mail_fetching", "content": "Fetching inbox...", "agent": "mail"}]
        for r in results:
            yield await _sse_event(r)
        engine_results = dispatch_session(state, prompt, model, confirm=confirm)
        for r in engine_results:
            yield await _sse_event({
                "type": r["type"],
                "content": r["content"],
                "agent": r.get("agent"),
                "emails": r.get("emails"),
            })
        if session_id != "_stateless":
            save_session(state)
        yield await _sse_done()
        return

    # Stateless single-turn agent — stream LLM tokens, then run plan
    agent = AGENTS[agent_name]
    messages = [
        {"role": "system", "content": agent.system_prompt()},
        {"role": "user", "content": prompt},
    ]
    from src.core.tools.schema import build_plan_schema
    schema = build_plan_schema(agent.tools)

    # Stream tokens from the LLM
    accumulated = ""
    try:
        stream = llm.stream_complete(messages, schema, model)
        async for token in stream:
            accumulated += token
            yield await _sse_token(token)
    except Exception as e:
        yield await _sse_event({"type": "error", "content": f"LLM error: {e}"})
        yield await _sse_done()
        return

    # Parse and execute plan
    try:
        from src.core.actions.action import Action, Plan
        action = Action.model_validate_json(accumulated)
        plan = Plan(actions=[action])
        results = _dispatch_plan_sync(plan, agent_name, model, state, interactive=False)
    except Exception as e:
        yield await _sse_event({"type": "error", "content": f"Plan error: {e}"})
        yield await _sse_done()
        return

    if session_id != "_stateless":
        save_session(state)

    for r in results:
        yield await _sse_event({
            "type": r["type"],
            "content": r.get("content", ""),
            "agent": r.get("agent"),
        })
    yield await _sse_done()


def _dispatch_plan_sync(plan, agent_name, model, state, interactive):
    """Synchronous plan dispatcher for streaming endpoint."""
    from src.core.actions.action import ActionType

    # Minimal re-implementation to avoid circular imports
    results = []
    for action in plan.actions:
        if action.type == ActionType.done:
            results.append({"type": "done", "content": "Session ended.", "agent": agent_name})
            break
        elif action.type in (ActionType.answer, ActionType.summary, ActionType.warning):
            results.append({"type": action.type.value, "content": action.content, "agent": agent_name})
        elif action.type == ActionType.note:
            from src.core.memory import note as mem_note
            mem_note(f"[note] {action.content}", agent=agent_name)
            results.append({"type": "note", "content": action.content, "agent": agent_name})
        elif action.type == ActionType.remember:
            from src.core.memory import note as mem_note
            mem_note(action.content, agent=agent_name)
            results.append({"type": "remember", "content": action.content, "agent": agent_name})
        elif action.type == ActionType.ask_user:
            results.append({"type": "ask_user", "content": action.content, "agent": agent_name})
        elif action.type == ActionType.command:
            results.append({
                "type": "confirm",
                "content": action.content,
                "agent": agent_name,
                "pending_confirm": action.content,
            })
        elif action.type == ActionType.web_search:
            from src.core.search import search_web
            try:
                result = search_web(action.content)
                answer_text = result.get("answer", "")
                if result.get("results"):
                    answer_text += "\n\n**Web Results:**\n" + "\n".join(
                        f"- [{r['title']}]({r['url']})" for r in result["results"][:5]
                    )
            except TimeoutError:
                answer_text = "Search timed out. Please try again."
            except Exception as e:
                answer_text = f"Search failed: {e}"
            results.append({"type": "answer", "content": answer_text, "agent": agent_name})
        elif action.type == ActionType.personal_data:
            from src.core.memory import recall
            memories = recall(action.content, state.user_id, top_k=5)
            if not memories:
                answer_text = "I don't have any memories on that topic."
            else:
                lines = [f"- {m['content']} (relevance: {round(m['score'] * 100)}%" for m in memories]
                answer_text = "Here's what I remember:\n" + "\n".join(lines)
            results.append({"type": "answer", "content": answer_text, "agent": agent_name})
    return results


@router.post("/api/chat/stream")
async def chat_stream(request: Request):
    """SSE streaming version of /api/chat. Streams LLM tokens as they arrive."""
    try:
        body = ChatRequest.model_validate_json(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    payload = jwt_required(request)
    user_id = payload["user_id"]
    session_id = get_session_id(request) or body.session_id

    return StreamingResponse(
        _chat_stream_iterator(body.prompt, body.model, user_id, session_id, body.confirm),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
