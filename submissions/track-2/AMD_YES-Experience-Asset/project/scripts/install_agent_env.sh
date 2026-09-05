#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
REPO="${REPO:-$ROOT/repo}"
VENV="${AGENT_VENV:-$ROOT/venvs/agent}"

if [[ "$ROOT" != /workspace/* ]]; then
  echo "ERROR: keep the environment under /workspace so it survives pod rebuilds."
  exit 1
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$REPO/requirements-agent.txt"

echo "Agent environment installed."
echo "Activate with: source $VENV/bin/activate"
