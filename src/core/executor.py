"""Agent dispatch — routes prompts to subagents and executes their plans.

Session state is minimal: only the mail inbox (MailEngine) persists across
turns. Routing, model selection, and conversation context are all per-request.
"""
import typer
from collections.abc import Callable

from core.actions.action import ActionType, Action, Plan
from core.actions.mail import refresh_mail, read_emails
from core.agents import AGENTS
from core.agents.head import HeadAgent
from core.config import IMAP_ACCOUNTS, MAIL_SUMMARY_COUNT, TARGET_MAILBOX
from core.docker import run_in_docker
from core.mail_engine import MailEngine
from core.llm import default_adapter
from core.memory import remember
from core.session_store import SessionState


# -- Stateless CLI helpers -------------------------------------------------

def print_thinking(scope: str = "agent"):
    print(f"[thinking] {scope}...", flush=True)


def fetch_inbox(action: Action) -> tuple[list[dict], str]:
    """Legacy helper for direct CLI use."""
    print("[mail] getting mail...", flush=True)
    refresh_mail()
    inbox = read_emails(
        action.count or MAIL_SUMMARY_COUNT,
        action.unread_only,
        mailbox=TARGET_MAILBOX,
        account_name=action.account,
    )
    label = "unread" if action.unread_only else "all"
    return inbox, label


def mail_loop(action: Action, model: str, mail_system: str | Callable[[], str] | None = None):
    """Compatibility wrapper around MailEngine for stateless CLI mode (config-based IMAP only)."""
    engine = MailEngine(model=model)  # uses IMAP_ACCOUNTS from config
    engine.fetch(count=action.count, unread_only=action.unread_only, account=action.account)
    print(engine.display(), flush=True)

    while True:
        user_input = typer.prompt("\n> ")
        if user_input.lower() in ("done", "exit", "quit"):
            print("[done] mail session ended.", flush=True)
            return

        results = engine.handle(user_input, interactive=True)
        for result in results:
            if result["type"] == "confirm":
                if typer.confirm(result["content"]):
                    pending = Action(**result["pending"])
                    print(engine.execute(pending), flush=True)
                    print(engine.display(), flush=True)
                else:
                    print("[mail] skipped.", flush=True)
            else:
                print(result.get("content", ""), flush=True)

        if any(result["type"] == "done" for result in results):
            return


def execute(
    messages: list[dict],
    model: str,
    mail_system: str | Callable[[], str] | None = None,
):
    """Legacy one-shot entry point."""
    print_thinking("agent")
    content = default_adapter.complete(messages, Action.model_json_schema(), model)
    action = Action.model_validate_json(content)

    if action.type == ActionType.done:
        print("[done] session ended.", flush=True)
    elif action.type == ActionType.misc:
        print(f"[misc] {action.content}", flush=True)
    elif action.type == ActionType.answer:
        print(f"[answer] {action.content}", flush=True)
    elif action.type == ActionType.summary:
        print(f"[summary] {action.content}", flush=True)
    elif action.type == ActionType.warning:
        print(f"[warning] {action.content}", flush=True)
    elif action.type == ActionType.note:
        remember(f"[note] {action.content}")
        print(f"[note] saved: {action.content}", flush=True)
    elif action.type == ActionType.remember:
        remember(action.content)
        print(f"[memory] saved: {action.content}", flush=True)
    elif action.type == ActionType.command:
        typer.confirm(f"Run in sandbox: {action.content!r}?", abort=True)
        output = run_in_docker(action.content)
        print(f"[output] {output}", flush=True)
    elif action.type == ActionType.mail_read:
        mail_loop(action, model, mail_system)
    elif action.type == ActionType.ask_user:
        print(f"[?] {action.content}", flush=True)


# -- Session dispatch -------------------------------------------------------

_head_agent = HeadAgent()


def dispatch_session(
    state: SessionState,
    prompt: str,
    model: str,
    *,
    interactive: bool = False,
) -> list[dict]:
    """Route a prompt and return structured results.

    Mail state persists in the session. All other routing and context is
    stateless — resolved fresh on each request.
    """
    # If a mail session is active, delegate directly to the engine
    if state.mail_engine:
        engine = MailEngine.from_dict(state.mail_engine, imap_accounts=state.imap_accounts)
        results = engine.handle(prompt, interactive=interactive)
        state.mail_engine = engine.to_dict()

        if any(r["type"] == "done" for r in results):
            state.mail_engine = None

        return results

    # Fresh routing
    route = _head_agent.route(prompt, model)
    agent_name = route.agent

    if agent_name == "mail":
        # Initial mail fetch — create engine and populate inbox
        engine = MailEngine(model=model, imap_accounts=state.imap_accounts)
        engine.fetch()
        state.mail_engine = engine.to_dict()
        return [engine._mail_list_result(f"Fetched {len(engine.inbox)} emails")]

    # Stateless single-turn agents (answer, command, etc.)
    agent = AGENTS[agent_name]
    context = [
        {"role": "system", "content": agent.system_prompt()},
        {"role": "user", "content": prompt},
    ]
    plan = agent.plan(context, model)
    return _dispatch_plan(plan, agent_name, model, interactive=interactive)


def _dispatch_plan(
    plan: Plan,
    agent_name: str,
    model: str,
    *,
    interactive: bool = False,
) -> list[dict]:
    """Execute a plan from a stateless agent."""
    results: list[dict] = []

    for action in plan.actions:
        if action.type == ActionType.done:
            results.append({"type": "done", "content": "Session ended.", "agent": agent_name})
            break

        elif action.type in (ActionType.answer, ActionType.summary, ActionType.warning):
            results.append({"type": action.type.value, "content": action.content, "agent": agent_name})

        elif action.type == ActionType.note:
            remember(f"[note] {action.content}", agent=agent_name)
            results.append({"type": "note", "content": action.content, "agent": agent_name})

        elif action.type == ActionType.remember:
            remember(action.content, agent=agent_name)
            results.append({"type": "remember", "content": action.content, "agent": agent_name})

        elif action.type == ActionType.ask_user:
            results.append({"type": "ask_user", "content": action.content, "agent": agent_name})
            break

        elif action.type == ActionType.command:
            if interactive:
                typer.confirm(f"Run in sandbox: {action.content!r}?", abort=True)
                output = run_in_docker(action.content)
                results.append({"type": "output", "content": output, "agent": agent_name})
            else:
                results.append({
                    "type": "confirm",
                    "content": action.content,
                    "agent": agent_name,
                    "pending_confirm": action.content,
                })
                break

        elif action.type == ActionType.web_search:
            results.append({"type": "web_search", "content": f"Web search not yet implemented. Query: {action.content}", "agent": agent_name})

        elif action.type == ActionType.personal_data:
            results.append({"type": "personal_data", "content": f"Personal data access not yet implemented.", "agent": agent_name})

    return results
