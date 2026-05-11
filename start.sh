#!/usr/bin/env bash
# Start MyAgent server with outside-accessible binding.
# Set MYDEVTEAM_API_KEY before running in production.
#
# Usage:
#   ./start.sh                          # defaults: 0.0.0.0:8000, no auth
#   MYDEVTEAM_API_KEY=secret ./start.sh # with API key protection
#   PORT=9000 ./start.sh                # custom port

set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ -x ".venv/bin/python" ] && [ "${PYTHON_BIN}" = "python3" ]; then
    PYTHON_BIN=".venv/bin/python"
fi

if [ -z "${MYDEVTEAM_API_KEY:-}" ]; then
    echo "WARNING: MYDEVTEAM_API_KEY is not set. Server is unprotected." >&2
fi

exec "$PYTHON_BIN" -m uvicorn src.gateway.__main__:app --host "$HOST" --port "$PORT"
