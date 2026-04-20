#!/usr/bin/env bash
# Start MyDevTeam server with outside-accessible binding.
# Set MYDEVTEAM_API_KEY before running in production.
#
# Usage:
#   ./start.sh                          # defaults: 0.0.0.0:8000, no auth
#   MYDEVTEAM_API_KEY=secret ./start.sh # with API key protection
#   PORT=9000 ./start.sh                # custom port

set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
UVICORN_BIN="${UVICORN_BIN:-uvicorn}"

if [ -x ".venv/bin/uvicorn" ] && [ "${UVICORN_BIN}" = "uvicorn" ]; then
    UVICORN_BIN=".venv/bin/uvicorn"
fi

if [ -z "${MYDEVTEAM_API_KEY:-}" ]; then
    echo "WARNING: MYDEVTEAM_API_KEY is not set. Server is unprotected." >&2
fi

exec "$UVICORN_BIN" server.__main__:app --host "$HOST" --port "$PORT"
