"""All tool definitions in one place.

Import individual tools or pre-built tool sets (MAIL_TOOLS, COMMAND_TOOLS, etc.)
when declaring an agent's capabilities.
"""
from .defs import ToolDef, ParamDef

# ── Mail ──────────────────────────────────────────────────────────────────────

MAIL_READ = ToolDef(
    name="mail_read",
    description="Fetch emails from the inbox.",
    params=[
        ParamDef("count",       "integer", "Number of emails to fetch.",          default=10),
        ParamDef("unread_only", "boolean", "Only fetch unread emails.",            default=True),
    ],
)

MAIL_READ_ALL = ToolDef(
    name="mail_read_all",
    description="Fetch all emails from the mailbox without any limit. Use for full inbox sync before local querying. Specify the folder (mailbox) to read from.",
    params=[
        ParamDef("mailbox", "string", "The IMAP mailbox/folder name to read from.", default="INBOX"),
    ],
)

MAIL_CREATE_FOLDER = ToolDef(
    name="mail_create_folder",
    description="Create a new IMAP folder/mailbox.",
    params=[
        ParamDef("folder_name", "string", "The name of the folder to create.", required=True),
    ],
)

MAIL_MOVE = ToolDef(
    name="mail_move",
    description="Move or delete emails by index number. Set indices to the 1-based email numbers. Use folder='Trash' to delete.",
    params=[
        ParamDef("folder", "string", "Destination mailbox folder name.", required=True),
    ],
)

# ── Execution ─────────────────────────────────────────────────────────────────

COMMAND = ToolDef(
    name="command",
    description="Run a shell command inside an isolated Docker sandbox.",
    params=[
        ParamDef("content", "string", "The shell command to execute.", required=True),
    ],
)

# ── Conversation ──────────────────────────────────────────────────────────────

ANSWER = ToolDef(
    name="answer",
    description="Respond to the user with text.",
    params=[ParamDef("content", "string", "The response text.", required=True)],
)

SUMMARY = ToolDef(
    name="summary",
    description="Summarize content for the user.",
    params=[ParamDef("content", "string", "The summary text.", required=True)],
)

ASK_USER = ToolDef(
    name="ask_user",
    description="Pause and ask the user a clarifying question before continuing.",
    params=[ParamDef("content", "string", "The question to ask.", required=True)],
)

WARNING = ToolDef(
    name="warning",
    description="Surface a concern, limitation, or potential issue to the user.",
    params=[ParamDef("content", "string", "The warning message.", required=True)],
)

# ── Memory ────────────────────────────────────────────────────────────────────

NOTE = ToolDef(
    name="note",
    description="Save a brief note about a specific item (e.g. an email) to memory.",
    params=[ParamDef("content", "string", "The note text.", required=True)],
)

REMEMBER = ToolDef(
    name="remember",
    description="Save a general preference or fact to long-term memory.",
    params=[ParamDef("content", "string", "The fact to remember.", required=True)],
)

# ── Knowledge ─────────────────────────────────────────────────────────────────

WEB_SEARCH = ToolDef(
    name="web_search",
    description="Search the web for up-to-date information.",
    params=[
        ParamDef("content", "string", "The search query.", required=True),
    ],
)

PERSONAL_DATA = ToolDef(
    name="personal_data",
    description="Retrieve personal data or facts stored about the user.",
    params=[
        ParamDef("content", "string", "What to look up.", required=True),
    ],
)

# ── Control ───────────────────────────────────────────────────────────────────

DONE = ToolDef(
    name="done",
    description="End the current agent session cleanly.",
)

# ── Pre-built tool sets (use these when declaring agents) ─────────────────────

MAIL_TOOLS:    list[ToolDef] = [MAIL_READ, MAIL_READ_ALL, MAIL_CREATE_FOLDER, MAIL_MOVE, SUMMARY, ANSWER, ASK_USER, NOTE, REMEMBER, WARNING, DONE]
COMMAND_TOOLS: list[ToolDef] = [COMMAND, ANSWER, ASK_USER, WARNING, DONE]
ANSWER_TOOLS:  list[ToolDef] = [ANSWER, SUMMARY, NOTE, REMEMBER, ASK_USER, WEB_SEARCH, PERSONAL_DATA, WARNING, DONE]
