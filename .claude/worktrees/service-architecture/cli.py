import typer
from typing import Optional

from actions.mail import fetch_mailboxes
from config import DEFAULT_MODEL, TARGET_MAILBOX, MAIL_SUMMARY_COUNT
from memory import load_memory
from executor import execute, dispatch_session
from session_store import load_session, save_session

app = typer.Typer()

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
- Use mail_read when the task should enter the email workflow. The email workflow keeps its own context.
- Use misc instead of forcing a bad command or email action when the request does not map cleanly.
- For top-level actions, prefer continue_conversation=false.
"""

MAIL_SYSTEM = """You are managing the user's inbox. Respond with a single action.

Action types:
- summary: summarize the email subjects. put summary in content.
- mail_move: move emails to folder. use filter_from or filter_subject to match.
- mail_save: save email to Saved folder. use filter_from or filter_subject to match.
- ask_user: ask the user what they want to do. put question in content.
- note: save a note about an email to memory. put note in content.
- remember: save a user preference for future sessions. put fact in content.
- warning: surface a concern or limitation. put message in content.
- done: end the mail session.

Set continue_conversation=true after each action to keep the session going.
Set continue_conversation=false only when the user is done or inbox is empty.
"""


def build_messages(prompt: str) -> list[dict]:
    memory = load_memory()
    memory_block = "\n".join(f"- {f}" for f in memory) if memory else "None yet."
    system = MAIN_SYSTEM + f"\nMemory:\n{memory_block}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def build_mail_system() -> str:
    memory = load_memory()
    memory_block = "\n".join(f"- {f}" for f in memory) if memory else "None yet."
    mailboxes = fetch_mailboxes(exclude=TARGET_MAILBOX)
    mailbox_block = "\n".join(f"- {m}" for m in mailboxes) if mailboxes else "None available"
    return MAIL_SYSTEM + (
        f"\nSource mailbox:\n- {TARGET_MAILBOX}"
        f"\n\nAvailable destination mailboxes:\n{mailbox_block}"
        f"\n\nSummarize only the top {MAIL_SUMMARY_COUNT} email subjects from the source mailbox."
        f"\n\nMemory:\n{memory_block}"
    )


@app.command()
def chat(
    prompt: str,
    model: str = DEFAULT_MODEL,
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session ID for multi-turn mode (uses sessions.db)"),
):
    """Send a task to the assistant."""
    if session:
        state = load_session(session, model)
        results = dispatch_session(state, prompt, interactive=True)
        save_session(state)
        for r in results:
            print(f"[{r['type']}] {r['content']}", flush=True)
    else:
        execute(build_messages(prompt), model, build_mail_system)


@app.command()
def mailboxes():
    """List exact Apple Mail mailbox paths."""
    print(f"Configured source mailbox: {TARGET_MAILBOX}")
    print("Mailboxes:")
    for mailbox in fetch_mailboxes():
        print(f"- {mailbox}")


if __name__ == "__main__":
    app()
