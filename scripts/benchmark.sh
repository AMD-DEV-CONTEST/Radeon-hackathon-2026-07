#!/bin/bash
# Bunker Benchmark Runner
# Delegates to Python script for cross-platform consistency and JSON output.
# Usage: ./scripts/benchmark.sh [--model MODEL] [--iterations N] [--vllm-url URL] ...

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/benchmark.py"

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
    echo "Error: Python benchmark script not found at ${PYTHON_SCRIPT}" >&2
    exit 1
fi

# Pass all arguments to Python script
exec python3 "${PYTHON_SCRIPT}" "$@"