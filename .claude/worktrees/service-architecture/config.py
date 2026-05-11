import os

DEFAULT_MODEL = "qwen2.5:3b"
TARGET_MAILBOX = "Inbox"
MAIL_SUMMARY_COUNT = 10

# Server config
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
API_KEY = os.environ.get("MAC_AGENT_API_KEY", "")  # empty = no auth (local dev only)
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
