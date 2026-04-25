import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
TARGET_MAILBOX = "Inbox"
MAIL_SUMMARY_COUNT = 10

# Server config
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
API_KEY = os.environ.get("MYDEVTEAM_API_KEY", "")  # empty = no auth (local dev only)
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "168"))  # 7 days

# Admin emails — users with these emails are auto-promoted to admin on login/register
ADMIN_EMAILS: list[str] = [
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
]

# Redis URL for session credential storage
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# Search provider: "duckduckgo" | "searx" | "google"
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "duckduckgo")
SEARCH_SEARX_URL = os.environ.get("SEARCH_SEARX_URL", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX", "")

# LLM backend for search answers
SEARCH_LLM_PROVIDER = os.environ.get("SEARCH_LLM_PROVIDER", "ollama")
SEARCH_LLM_MODEL = os.environ.get("SEARCH_LLM_MODEL", "qwen3:8b")
SEARCH_OPENAI_MODEL = os.environ.get("SEARCH_OPENAI_MODEL", "gpt-4o-mini")
SEARCH_ANTHROPIC_MODEL = os.environ.get("SEARCH_ANTHROPIC_MODEL", "claude-sonnet-4-6")

# IMAP accounts — discovered from IMAP_<NAME>_HOST/USER/PASS env vars
IMAP_ACCOUNTS: list[dict] = []
_seen = set()
for key in os.environ:
    if key.startswith("IMAP_") and key.endswith("_HOST"):
        name = key[5:-5]  # e.g. "GMAIL" from "IMAP_GMAIL_HOST"
        if name not in _seen:
            _seen.add(name)
            IMAP_ACCOUNTS.append({
                "name": name.capitalize(),
                "host": os.environ[key],
                "user": os.environ.get(f"IMAP_{name}_USER", ""),
                "password": os.environ.get(f"IMAP_{name}_PASS", ""),
                "port": int(os.environ.get(f"IMAP_{name}_PORT", 993)),
            })