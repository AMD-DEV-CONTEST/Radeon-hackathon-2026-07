#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

exec /workspace/venv/bin/python -m src.web --host "${AGENT_HOST:-127.0.0.1}" --port "${AGENT_PORT:-7860}"
