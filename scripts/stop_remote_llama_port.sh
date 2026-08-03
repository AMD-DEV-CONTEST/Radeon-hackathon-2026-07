#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <host> <port> [user]"
  exit 1
fi

HOST="$1"
PORT="$2"
USER_NAME="${3:-${REMOTE_USER:-cesarops}}"

ssh -o BatchMode=yes -o ConnectTimeout=8 "${USER_NAME}@${HOST}" \
  "bash -lc \"fuser -k ${PORT}/tcp 2>/dev/null; pkill -f 'llama-server.*--port ${PORT}' 2>/dev/null; pkill -f 'koboldcpp.*--port ${PORT}' 2>/dev/null; true\""

echo "[ok] stopped processes on ${HOST}:${PORT}"
