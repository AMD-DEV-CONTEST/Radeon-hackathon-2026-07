#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Expected worker Python at $PYTHON. Create the venv before starting the worker." >&2
  exit 1
fi

args=()
if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  args+=(--orchestrator-url "$ORCHESTRATOR_URL")
fi
if [[ -n "${AGENT_TYPE:-}" ]]; then
  args+=(--agent-type "$AGENT_TYPE")
fi
if [[ -n "${WORKER_NAME:-}" ]]; then
  args+=(--name "$WORKER_NAME")
fi
if [[ -n "${WORKSPACE_ROOT:-}" ]]; then
  args+=(--workspace-root "$WORKSPACE_ROOT")
fi
args+=(--max-concurrency "${MAX_CONCURRENCY:-1}" run)

exec "$PYTHON" "$PROJECT_ROOT/worker/worker_cli.py" "${args[@]}"
