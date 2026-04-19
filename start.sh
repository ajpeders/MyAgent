#!/usr/bin/env bash
# Start mac-agent server with outside-accessible binding.
# Set MAC_AGENT_API_KEY before running in production.
#
# Usage:
#   ./start.sh                          # defaults: 0.0.0.0:8000, no auth
#   MAC_AGENT_API_KEY=secret ./start.sh # with API key protection
#   PORT=9000 ./start.sh                # custom port

set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [ -z "${MAC_AGENT_API_KEY:-}" ]; then
    echo "WARNING: MAC_AGENT_API_KEY is not set. Server is unprotected." >&2
fi

exec uvicorn server:app --host "$HOST" --port "$PORT"
