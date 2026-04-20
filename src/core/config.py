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

# Redis URL for session credential storage
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

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
