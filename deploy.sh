#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN=""
for candidate in "${PROJECT_ROOT}/.venv/bin/python" python3 python; do
    if [[ "${candidate}" == */* ]]; then
        [[ -x "${candidate}" ]] || continue
    else
        command -v "${candidate}" >/dev/null 2>&1 || continue
    fi
    if "${candidate}" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
        PYTHON_BIN="${candidate}"
        break
    fi
done

[[ -n "${PYTHON_BIN}" ]] || {
    echo "ERROR: Python 3.11 or newer is required." >&2
    exit 1
}

exec "${PYTHON_BIN}" "${PROJECT_ROOT}/deploy/deploy.py" "$@"
