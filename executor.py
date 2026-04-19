import typer
from collections.abc import Callable

from actions.action import ActionType, Action, Plan
from actions.mail import refresh_mail, read_emails, move_emails, email_matches, emails_to_text
from agents import AGENTS
from agents.base import AgentDef
from agents.head import HeadAgent
from config import TARGET_MAILBOX, MAIL_SUMMARY_COUNT
from llm import default_adapter
from memory import remember
from docker import run_in_docker
from session_store import SessionState


# ── Stateless CLI helpers ──────────────────────────────────────────────────────

def print_thinking(scope: str = "agent"):
    print(f"[thinking] {scope}...", flush=True)


def llm_action(messages: list[dict], model: str) -> Action:
    content = default_adapter.complete(messages, Action.model_json_schema(), model)
    return Action.model_validate_json(content)


def initial_mail_messages(inbox: list[dict], label: str, mail_system: str) -> list[dict]:
    return [
        {"role": "system", "content": mail_system},
        {"role": "user", "content": f"Emails ({len(inbox)} {label}):\n{emails_to_text(inbox)}\n\nSummarize and ask what I want to do."},
    ]


def fetch_inbox(action: Action) -> tuple[list[dict], str]:
    print("[mail] getting mail...", flush=True)
    refresh_mail()
    inbox = read_emails(MAIL_SUMMARY_COUNT, action.unread_only, mailbox=TARGET_MAILBOX)
    label = "unread" if action.unread_only else "all"
    return inbox, label


def resolve_mail_system(mail_system: str | Callable[[], str]) -> str:
    return mail_system() if callable(mail_system) else mail_system


def mail_loop(action: Action, model: str, mail_system: str | Callable[[], str]):
    """Isolated context for the mail session."""
    inbox, label = fetch_inbox(action)
    print(f"[mail] fetched {len(inbox)} {label} emails", flush=True)

    messages = initial_mail_messages(inbox, label, resolve_mail_system(mail_system))

    while True:
        print_thinking("mail")
        action = llm_action(messages, model)
        messages.append({"role": "assistant", "content": action.model_dump_json()})

        if action.type == ActionType.done:
            print("[done] mail session ended.", flush=True)
            break

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

        elif action.type == ActionType.mail_move:
            typer.confirm(f"Move emails (from={action.filter_from!r}, subject={action.filter_subject!r}) to {action.folder!r}?", abort=True)
            moved = move_emails(action.filter_from, action.filter_subject, action.folder, mailbox=TARGET_MAILBOX)
            inbox[:] = [e for e in inbox if not email_matches(e, action.filter_from, action.filter_subject)]
            result = f"Moved {moved} emails to {action.folder} — {len(inbox)} remaining"
            print(f"[mail_move] {result}", flush=True)
            messages.append({"role": "user", "content": result})
            continue

        elif action.type == ActionType.mail_save:
            typer.confirm(f"Save email (from={action.filter_from!r}, subject={action.filter_subject!r}) to Saved?", abort=True)
            moved = move_emails(action.filter_from, action.filter_subject, "Saved", mailbox=TARGET_MAILBOX)
            inbox[:] = [e for e in inbox if not email_matches(e, action.filter_from, action.filter_subject)]
            result = f"Saved {moved} emails — {len(inbox)} remaining"
            print(f"[mail_save] {result}", flush=True)
            messages.append({"role": "user", "content": result})
            continue

        elif action.type == ActionType.ask_user:
            print(f"[?] {action.content}", flush=True)
            user_input = typer.prompt("")
            messages.append({
                "role": "user",
                "content": f"{user_input}\n\nRemaining emails ({len(inbox)}):\n{emails_to_text(inbox)}"
            })
            continue

        if not action.continue_conversation or not inbox:
            break


def execute(messages: list[dict], model: str, mail_system: str | Callable[[], str]):
    """Run one top-level action. The mail workflow owns its own loop and context."""
    print_thinking("agent")
    action = llm_action(messages, model)

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


# ── Action dispatch (Agent->>Exec in the sequence diagram) ────────────────────

def resolve_pending(state: SessionState, *, interactive: bool = False) -> list[dict]:
    """Execute a previously-confirmed pending action (Exec->>Ext)."""
    action = Action(**state.pending)
    state.pending = None
    results: list[dict] = []

    if action.type == ActionType.command:
        if interactive:
            typer.confirm(f"Run in sandbox: {action.content!r}?", abort=True)
        output = run_in_docker(action.content)
        results.append({"type": "output", "content": output, "agent": state.active_agent})

    elif action.type == ActionType.mail_move:
        if interactive:
            typer.confirm(f"Move emails (from={action.filter_from!r}, subject={action.filter_subject!r}) to {action.folder!r}?", abort=True)
        moved = move_emails(action.filter_from, action.filter_subject, action.folder)
        state.inbox[:] = [e for e in state.inbox if not email_matches(e, action.filter_from, action.filter_subject)]
        results.append({
            "type": "mail_move",
            "content": f"Moved {moved} emails to {action.folder} — {len(state.inbox)} remaining",
            "agent": "mail",
        })

    elif action.type == ActionType.mail_save:
        if interactive:
            typer.confirm(f"Save email (from={action.filter_from!r}, subject={action.filter_subject!r}) to Saved?", abort=True)
        moved = move_emails(action.filter_from, action.filter_subject, "Saved")
        state.inbox[:] = [e for e in state.inbox if not email_matches(e, action.filter_from, action.filter_subject)]
        results.append({
            "type": "mail_save",
            "content": f"Saved {moved} emails — {len(state.inbox)} remaining",
            "agent": "mail",
        })

    return results


def dispatch_actions(
    plan: Plan,
    state: SessionState,
    agent: AgentDef,
    context: list[dict],
    *,
    interactive: bool = False,
) -> list[dict]:
    """Dispatch actions from a Plan. Calls agent.plan() for replanning (Exec->>Agent)."""
    results: list[dict] = []
    agent_name = agent.name

    for action in plan.actions:
        if action.type == ActionType.done:
            results.append({"type": "done", "content": "Session ended.", "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})
            state.active_agent = None
            break

        elif action.type in (ActionType.answer, ActionType.summary, ActionType.warning):
            results.append({"type": action.type.value, "content": action.content, "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})

        elif action.type == ActionType.note:
            remember(f"[note] {action.content}", agent=agent_name)
            results.append({"type": "note", "content": action.content, "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})

        elif action.type == ActionType.remember:
            remember(action.content, agent=agent_name)
            results.append({"type": "remember", "content": action.content, "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})

        elif action.type == ActionType.ask_user:
            results.append({"type": "ask_user", "content": action.content, "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})
            break  # wait for user reply

        elif action.type == ActionType.command:
            if interactive:
                typer.confirm(f"Run in sandbox: {action.content!r}?", abort=True)
                output = run_in_docker(action.content)
                results.append({"type": "output", "content": output, "agent": agent_name})
                context.append({"role": "assistant", "content": action.model_dump_json()})
            else:
                state.pending = action.model_dump()
                results.append({
                    "type": "confirm",
                    "content": action.content,
                    "agent": agent_name,
                    "pending_confirm": action.content,
                })
                break

        elif action.type == ActionType.mail_read:
            refresh_mail()
            state.inbox.clear()
            state.inbox.extend(read_emails(action.count, action.unread_only))
            label = "unread" if action.unread_only else "all"
            results.append({"type": "mail_read", "content": f"Fetched {len(state.inbox)} {label} emails", "agent": "mail"})
            context.append({"role": "assistant", "content": action.model_dump_json()})
            # Exec->>Agent: replan with result
            context.append({
                "role": "user",
                "content": f"Emails ({len(state.inbox)} {label}):\n{emails_to_text(state.inbox)}\n\nContinue.",
            })
            follow_up = agent.plan(context, state.model)
            plan.actions.extend(follow_up.actions)

        elif action.type == ActionType.mail_move:
            if interactive:
                typer.confirm(f"Move emails (from={action.filter_from!r}, subject={action.filter_subject!r}) to {action.folder!r}?", abort=True)
                moved = move_emails(action.filter_from, action.filter_subject, action.folder)
                state.inbox[:] = [e for e in state.inbox if not email_matches(e, action.filter_from, action.filter_subject)]
                msg = f"Moved {moved} emails to {action.folder} — {len(state.inbox)} remaining"
                results.append({"type": "mail_move", "content": msg, "agent": "mail"})
                context.append({"role": "assistant", "content": action.model_dump_json()})
                context.append({"role": "user", "content": msg})
            else:
                state.pending = action.model_dump()
                results.append({
                    "type": "confirm",
                    "content": f"Move emails (from={action.filter_from!r}, subject={action.filter_subject!r}) to {action.folder!r}?",
                    "agent": "mail",
                    "pending_confirm": "mail_move",
                })
                break

        elif action.type == ActionType.mail_save:
            if interactive:
                typer.confirm(f"Save email (from={action.filter_from!r}, subject={action.filter_subject!r}) to Saved?", abort=True)
                moved = move_emails(action.filter_from, action.filter_subject, "Saved")
                state.inbox[:] = [e for e in state.inbox if not email_matches(e, action.filter_from, action.filter_subject)]
                msg = f"Saved {moved} emails — {len(state.inbox)} remaining"
                results.append({"type": "mail_save", "content": msg, "agent": "mail"})
                context.append({"role": "assistant", "content": action.model_dump_json()})
                context.append({"role": "user", "content": msg})
            else:
                state.pending = action.model_dump()
                results.append({
                    "type": "confirm",
                    "content": f"Save email (from={action.filter_from!r}, subject={action.filter_subject!r}) to Saved?",
                    "agent": "mail",
                    "pending_confirm": "mail_save",
                })
                break

        elif action.type == ActionType.web_search:
            # Stub: web search not yet implemented
            result = f"Web search not yet implemented. Query: {action.content}"
            results.append({"type": "web_search", "content": result, "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})
            context.append({"role": "user", "content": result})

        elif action.type == ActionType.personal_data:
            # Stub: personal data access not yet implemented
            result = f"Personal data access not yet implemented. Query: {action.content}"
            results.append({"type": "personal_data", "content": result, "agent": agent_name})
            context.append({"role": "assistant", "content": action.model_dump_json()})
            context.append({"role": "user", "content": result})

    return results


# ── Session coordination (Entry->>Store->>Agent->>Exec) ───────────────────────

_head_agent = HeadAgent()


def _get_agent_context(state: SessionState, agent_name: str) -> list[dict]:
    """Return the message history for a subagent, initialising it if needed."""
    if agent_name not in state.contexts:
        state.contexts[agent_name] = [
            {"role": "system", "content": AGENTS[agent_name].system_prompt()}
        ]
    return state.contexts[agent_name]


def dispatch_session(
    state: SessionState,
    prompt: str,
    *,
    interactive: bool = False,
    confirm: bool = False,
) -> list[dict]:
    """Shared multi-turn coordination for CLI and server.

    Follows the runtime flow from ARCHITECTURE.md:
      Entry → sessions.db → HeadAgent (if needed) → Agent.plan() → executor.dispatch_actions()
    """
    # --- Resolve pending confirmation (Exec->>Ext after Client confirms) ---
    if state.pending and confirm:
        return resolve_pending(state, interactive=interactive)

    # Clear stale pending state if not confirming
    if state.pending and not confirm:
        state.pending = None

    # --- Route via head agent if no active subagent ---
    if not state.active_agent:
        route = _head_agent.route(prompt, state.model)
        state.active_agent = route.agent

    # --- Agent calls LLM (Agent->>LLM in the sequence diagram) ---
    agent = AGENTS[state.active_agent]
    context = _get_agent_context(state, state.active_agent)
    context.append({"role": "user", "content": prompt})
    plan = agent.plan(context, state.model)

    # --- Executor dispatches actions (Agent->>Exec in the sequence diagram) ---
    return dispatch_actions(plan, state, agent, context, interactive=interactive)
