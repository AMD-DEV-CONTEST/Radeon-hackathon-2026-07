#!/usr/bin/env bash
# Run one deterministic, checkpoint-free Genesis scripted-agent episode.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: bash scripts/run_demo.sh

Runs one deterministic, checkpoint-free episode 0 through ScriptedExpertPolicy. This is a
simulation scripted-agent demo, not a pure-VLA or real-robot evaluation.

Environment overrides:
  DEMO_BACKEND=rocm     Genesis backend: rocm, cuda, or cpu (default: rocm)
  DEMO_OUTPUT=PATH      Output root (default: outputs/scripted-demo)
  PYTHON_BIN=python3    Python executable (default: python3)
EOF
  exit 0
fi

if [[ "$#" -ne 0 ]]; then
  echo "run_demo.sh accepts no positional arguments; use --help for environment overrides." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEMO_BACKEND="${DEMO_BACKEND:-rocm}"
DEMO_OUTPUT="${DEMO_OUTPUT:-${ROOT_DIR}/outputs/scripted-demo}"

case "${DEMO_BACKEND}" in rocm|cuda|cpu) ;; *)
  echo "DEMO_BACKEND must be rocm, cuda, or cpu." >&2
  exit 2
esac
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONDONTWRITEBYTECODE=1
cd "${ROOT_DIR}"

command=(
  "${PYTHON_BIN}" scripts/run_expert.py
  --config configs/baseline.toml
  --backend "${DEMO_BACKEND}"
  --episodes 1
  --start-episode 0
  --output "${DEMO_OUTPUT}"
  --record-video
  --fail-on-unsuccessful
)
exec "${command[@]}"
