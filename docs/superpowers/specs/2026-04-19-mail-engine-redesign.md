# Mail Engine Redesign

## Problem

The current mail loop delegates too much to the LLM: display, formatting, state tracking, intent parsing, and recommendations — all in one call with a growing conversation history. A small local model (qwen3:8b) can't reliably handle all of that, leading to:

- Hallucinated stale emails after deletes
- Inconsistent formatting
- Looping/repeating actions
- Lost state across turns
- Empty or malformed LLM responses

## Design

Replace `mail_loop()` with a `MailEngine` that owns all state, display, and execution. The LLM becomes a **stateless intent parser** called with fresh, minimal context each turn.

### Principle

**Code handles everything deterministic. LLM handles everything that requires understanding language or email content.**

## Architecture

```
User Input
    |
    v
MailEngine.handle(input)
    |
    v
LLM (stateless call)
    - System: "Parse this into actions"
    - User: current inbox + user input
    - Returns: Plan (list of Actions)
    |
    v
MailEngine.execute(plan)
    - Executes each action (IMAP ops)
    - Updates inbox cache
    - Renders display (deterministic)
    |
    v
Output to user (formatted by code, never by LLM)
```

## MailEngine

Central class that replaces `mail_loop()`. Owns inbox state, display, and execution.

```python
class MailEngine:
    inbox: list[dict]           # cached emails with UIDs, recommendations
    account: str                # active account or "" for all
    model: str                  # LLM model name

    def fetch(count, unread_only, account) -> list[dict]
    def display() -> str                    # deterministic formatted list
    def display_email(index) -> str         # show full body of one email
    def execute(action: Action) -> str      # run IMAP op, return result message
    def recommend(inbox) -> list[dict]      # LLM call: tag each email
    def parse_intent(user_input) -> Plan    # LLM call: classify user input
    def handle(user_input) -> list[str]     # main entry: parse + execute + display
```

### State

- `inbox` is the single source of truth for what emails exist
- After any mutation (delete, move), `inbox` is updated in-place
- Redisplay always renders from `inbox` — no LLM involved
- No conversation history accumulates — each LLM call is fresh

### Persistent Session

The engine supports a **long-lived session** stored in `SessionState`. Instead of fetching N emails per interaction, the session holds the full inbox and persists across requests.

- **Auto-refresh:** On each interaction, the engine checks for new emails and appends them to the cache. Only new UIDs are fetched (delta sync).
- **Session storage:** The `MailEngine` instance (inbox cache, page position, account) is serialized into `SessionState` and saved to SQLite between turns.
- **CLI:** A default `mail` session is created/resumed automatically. No `--session` flag needed for mail.
- **API:** Each `session_id` gets its own engine instance. The web client maintains a session and gets the same persistent inbox.

### Pagination

Large inboxes are handled by **windowed display**. The engine holds the full inbox but only shows and sends to the LLM a page at a time.

```
Full inbox: 1,000 emails (in engine cache)
Page size: 20 (configurable)
LLM sees: current page only

User: "next"     → advance to next page, display
User: "prev"     → go back a page
User: "page 5"   → jump to page 5
User: "delete 3" → references item 3 on current page
```

- **Display** shows page numbers: `[Page 1/50] Showing 1-20 of 1,000`
- **Recommendations** are generated per-page when that page is first viewed
- **Search/filter** operations (by sender, date) run against the full inbox in code, then paginate the results
- **Indices are page-relative** — "delete 1" means item 1 on the current page

### Display (deterministic)

`display()` renders the inbox as a formatted, numbered list:

```
 1. Discover Card — Your Discover Card was declined  [delete]
 2. Google — Security alert                          [keep]
 3. GitHub — SSH key added to your account            [keep]
```

Format is hardcoded. Recommendations come from `inbox[i]["recommendation"]` field set by the LLM on initial fetch. The LLM never generates this text.

`display_email(index)` shows the full body of a single email from the cache. No LLM call needed — body is already fetched and stored.

### Execution (deterministic)

`execute(action)` handles:
- `mail_move` — call `move_by_uids()`, remove from inbox cache, return result string
- `mail_read` — call IMAP fetch, replace inbox cache, call `recommend()` on new emails
- `answer` — look up email by index in cache, return body
- `done` — exit

All state mutations happen here. Confirmations for destructive actions (delete/move) are handled by the caller (CLI or API layer), not the engine.

## LLM Touchpoints

### 1. Recommendations (one call after each fetch)

Called once after fetching emails. Scans the full list and tags each.

**Input:**
```json
{
  "role": "system",
  "content": "You are an email classifier. For each email, return a recommendation: delete, keep, or save. Return JSON."
}
{
  "role": "user",
  "content": "Emails:\n1. FROM: Discover Card... SUBJECT: Your card was declined...\n2. FROM: Google... SUBJECT: Security alert...\n..."
}
```

**Output schema:**
```json
{
  "recommendations": [
    {"index": 1, "action": "delete", "reason": "promotional/transactional"},
    {"index": 2, "action": "keep", "reason": "security alert"}
  ]
}
```

The engine stores each recommendation on the corresponding inbox entry. If the LLM call fails or returns garbage, default all to `[keep]`.

### 2. Intent parsing (one call per user input)

Every user message goes through the LLM to get a structured Plan back. The LLM receives a **fresh context** each time — no conversation history.

**Input:**
```json
{
  "role": "system",
  "content": "You parse user email commands into actions. Current inbox is provided. Return a plan as JSON."
}
{
  "role": "user",
  "content": "User says: \"delete 1 and 3\"\n\nCurrent inbox:\n1. Discover Card — declined [delete]\n2. Google — Security alert [keep]\n3. GitHub — SSH key added [keep]"
}
```

**Output:** existing Plan schema (list of Actions)

### 3. Fuzzy queries (part of intent parsing)

"Delete all the marketing stuff" or "anything important?" — the LLM uses the inbox context to determine which emails match and returns appropriate actions. No separate call needed; this is handled by the intent parser.

## What Changes

| File | Change |
|------|--------|
| `executor.py` | Remove `mail_loop()`, `llm_mail_actions()`, `initial_mail_messages()`, `fetch_inbox()`, `resolve_mail_system()`. Add `MailEngine` class. |
| `executor.py` | `dispatch_actions()` uses `MailEngine` for mail action types instead of inline logic |
| `cli.py` | Remove `MAIL_SYSTEM` prompt. CLI creates `MailEngine` and calls `handle()` in a loop. |
| `agents/mail.py` | Simplify system prompt — it's now just an intent parser, not a conversation partner |
| `actions/action.py` | Add `index` field to Action for referencing emails by number |
| `tools/schema.py` | Update mail schema to reflect simplified action set |
| `server.py` | `ActionResponse` gains optional `emails`, `page`, `total_pages`, `total_emails` fields for structured mail data |
| `session_store.py` | `SessionState` stores serialized `MailEngine` (inbox cache, page, account) |

## What Stays the Same

- `actions/mail_imap.py` — IMAP backend unchanged
- `actions/mail.py` — dispatcher unchanged
- Action/Plan pydantic models — same structure, minor field additions
- UID-based safe operations — already implemented
- Multi-account support — already implemented
- `_resolve_folder()` — already implemented
- Confirmation flow (CLI: `typer.confirm`, API: `pending_confirm`) — unchanged

## CLI Flow Example

```
$ python cli.py chat "check my email"

[mail] Available accounts: Gmail, Yahoo
Which account? (or 'all'): all
[mail] Fetching emails...
[mail] 10 emails fetched. Getting recommendations...

 1. Discover Card — Your Discover Card was declined     [delete]
 2. Discover Card — A purchase exceeds your credit line [delete]
 3. Google — Security alert                             [keep]
 4. Google — Security alert                             [keep]
 5. GitHub — Google identity linked to your account     [keep]
 6. GitHub — SSH key added to your account              [keep]
 7. Google — Security alert                             [keep]
 8. Yahoo — Passkey removed from your account           [keep]
 9. Yahoo — App password generated                      [keep]
10. Yahoo — App password used to sign in                [keep]

> delete 1 and 2
Delete 2 emails? [y/N]: y
[mail] Deleted 2 emails — 8 remaining

 1. Google — Security alert                             [keep]
 2. Google — Security alert                             [keep]
 3. GitHub — Google identity linked to your account     [keep]
 4. GitHub — SSH key added to your account              [keep]
 5. Google — Security alert                             [keep]
 6. Yahoo — Passkey removed from your account           [keep]
 7. Yahoo — App password generated                      [keep]
 8. Yahoo — App password used to sign in                [keep]

> read 3
FROM: GitHub <noreply@github.com>
SUBJECT: A Google identity was just linked to your GitHub account
DATE: 2026-04-18

[full email body displayed from cache]

> delete all the marketing stuff
[thinking...]
Delete 0 emails? [y/N]: n
[mail] No marketing emails identified.

> done
[done] mail session ended.
```

## API Flow

`POST /chat` still returns `list[ActionResponse]`. The difference is internal — `dispatch_actions()` uses `MailEngine` instead of calling the LLM for display.

### Session-bound engine

Each API session gets its own `MailEngine` stored in `SessionState`:

```
POST /chat {session_id: "mail-1", prompt: "check email"}
  → load session → create/resume MailEngine → fetch + recommend
  → return: [{type: "mail_list", content: "...", emails: [...]}]

POST /chat {session_id: "mail-1", prompt: "delete 1"}
  → load session → resume MailEngine (inbox still cached)
  → return: [{type: "confirm", content: "Delete 1 email?", pending_confirm: "mail_move"}]

POST /chat {session_id: "mail-1", prompt: "", confirm: true}
  → execute pending → return: [{type: "mail_list", content: "updated list"}]
```

### Structured response for frontend

For mail actions, responses include structured data alongside the display string so the web frontend can render its own UI:

```json
{
  "type": "mail_list",
  "content": "formatted text for CLI fallback",
  "emails": [
    {"index": 1, "from": "Discover Card", "subject": "...", "date": "...", "recommendation": "delete"},
    {"index": 2, "from": "Google", "subject": "...", "date": "...", "recommendation": "keep"}
  ],
  "page": 1,
  "total_pages": 50,
  "total_emails": 1000
}
```

This lets the web agent build a rich interactive UI while the CLI just prints `content`. The engine produces both formats.

The confirmation flow via `pending_confirm` + `confirm=true` stays the same.

## Error Handling

- LLM returns empty/malformed response → default to `[Action(type=done)]`, print warning
- LLM recommendation call fails → default all emails to `[keep]`
- IMAP connection fails → print error, don't crash the session
- User references invalid email index → print "invalid index", redisplay

## Testing

Existing `LLMSequence` mock pattern works. Tests verify:
- `MailEngine.display()` produces correct format (no LLM needed)
- `MailEngine.execute()` updates inbox cache correctly (no LLM needed)
- `MailEngine.recommend()` maps LLM output to inbox entries
- `MailEngine.parse_intent()` converts LLM Plan to executable actions
- Full flow: fetch → recommend → user commands → execute → redisplay
