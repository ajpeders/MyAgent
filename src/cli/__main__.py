import typer
from typing import Optional

from core.actions.mail import fetch_mailboxes
from core.config import DEFAULT_MODEL, TARGET_MAILBOX
from core.executor import dispatch_session
from core.mail_engine import MailEngine
from core.memory import load_memory
from core.session_store import SessionState, load_session, save_session

app = typer.Typer()
DEFAULT_SESSION_ID = "mail"

MAIN_SYSTEM = """You are a helpful assistant. Respond with a single action.

Action types:
- misc: fallback for requests that do not fit another action cleanly. explain what to do next in content.
- mail_read: fetch emails. Only use when user explicitly asks about email.
- answer: respond to the user. put response in content.
- command: run shell command in sandbox. put command in content.
- warning: surface a concern or limitation. put message in content.
- done: end the session.

Rules:
- Do NOT reference emails unless the user asks about them.
- The top-level agent is stateless. Pick one best next action for this request only.
- Use mail_read when the task should enter the email workflow.
- Use misc instead of forcing a bad command or email action when the request does not map cleanly.
- For top-level actions, prefer continue_conversation=false.
"""


def build_messages(prompt: str) -> list[dict]:
    memory = load_memory()
    memory_block = "\n".join(f"- {fact}" for fact in memory) if memory else "None yet."
    system = MAIN_SYSTEM + f"\nMemory:\n{memory_block}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def _print_results(results: list[dict], state: SessionState | None = None) -> None:
    for result in results:
        rtype = result["type"]
        if rtype == "done":
            print("[done] session ended.", flush=True)
        elif rtype == "confirm" and result.get("pending"):
            if typer.confirm(result["content"]):
                _execute_pending(result["pending"], state)
            else:
                print("[mail] skipped.", flush=True)
        elif rtype in {"mail_list", "answer", "summary", "warning", "ask_user", "mail_move", "output", "note", "remember"}:
            print(result.get("content", ""), flush=True)


def _execute_pending(pending: dict, state: SessionState | None) -> None:
    """Execute a confirmed pending action on the mail engine."""
    from core.actions.action import Action
    if not state or not state.mail_engine:
        print("[mail] No active mail session.", flush=True)
        return
    engine = MailEngine.from_dict(state.mail_engine)
    action = Action(**pending)
    print(engine.execute(action), flush=True)
    state.mail_engine = engine.to_dict()
    save_session(state)
    print(engine.display(), flush=True)


@app.command()
def chat(
    prompt: str,
    model: str = DEFAULT_MODEL,
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session ID for multi-turn mode"),
):
    """Send a task to the assistant."""
    sid = session or DEFAULT_SESSION_ID
    state = load_session(sid)

    results = dispatch_session(state, prompt, model, interactive=True)
    save_session(state)
    _print_results(results, state)

    while state.mail_engine and not any(r["type"] == "done" for r in results):
        user_input = typer.prompt("\n> ")
        if user_input.lower() in ("done", "exit", "quit"):
            print("[done] mail session ended.", flush=True)
            state.mail_engine = None
            save_session(state)
            break

        results = dispatch_session(state, user_input, model, interactive=True)
        save_session(state)
        _print_results(results, state)


@app.command()
def mailboxes():
    """List exact Apple Mail mailbox paths."""
    print(f"Configured source mailbox: {TARGET_MAILBOX}")
    print("Mailboxes:")
    for mailbox in fetch_mailboxes():
        print(f"- {mailbox}")


@app.command()
def mail_status(session: str = DEFAULT_SESSION_ID):
    """Show the cached mail page for a session."""
    state = load_session(session)
    if not state.mail_engine:
        print("[mail] No active mail session.", flush=True)
        return
    engine = MailEngine.from_dict(state.mail_engine)
    print(engine.display(), flush=True)


if __name__ == "__main__":
    app()
