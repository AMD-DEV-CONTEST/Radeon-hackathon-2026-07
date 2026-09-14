#!/usr/bin/env bash
# Thin interpreter shim so every pipeline entry point calls Python the same way.
# Prefers a project-local .venv when present, otherwise the system python3.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "${ROOT}/.venv/bin/python3" ]; then
  exec "${ROOT}/.venv/bin/python3" "$@"
fi
exec python3 "$@"
