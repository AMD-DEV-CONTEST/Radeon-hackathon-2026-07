#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  python_bin="$PYTHON_BIN"
elif [[ -x /opt/venv/bin/python ]]; then
  python_bin=/opt/venv/bin/python
else
  python_bin=.venv/bin/python
fi

if ! curl -fsS --max-time 10 http://127.0.0.1:8000/v1/models >/dev/null; then
  echo "ERROR: local vLLM is not ready at http://127.0.0.1:8000/v1." >&2
  exit 2
fi

exec "$python_bin" benchmarks/amd_concurrency.py "$@"
