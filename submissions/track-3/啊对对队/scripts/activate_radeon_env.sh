#!/usr/bin/env bash

# Source this file so subsequent commands use a Python environment with ROCm PyTorch.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

is_rocm_env() {
  local candidate="$1"
  [[ -x "${candidate}/bin/python" ]] && \
    "${candidate}/bin/python" -c \
      'import torch; assert torch.version.hip and torch.cuda.is_available()' \
      >/dev/null 2>&1
}

if [[ -n "${PARCEL_SORTER_VENV:-}" ]]; then
  candidates=("${PARCEL_SORTER_VENV}")
else
  current_prefix="$(python3 -c 'import sys; print(sys.prefix)' 2>/dev/null || true)"
  candidates=()
  if [[ -n "${current_prefix}" ]]; then
    candidates+=("${current_prefix}")
  fi
  candidates+=("${ROOT_DIR}/.venv" "/workspace/rdna")
fi

for candidate in "${candidates[@]}"; do
  if is_rocm_env "${candidate}"; then
    if [[ -f "${candidate}/bin/activate" ]]; then
      # shellcheck disable=SC1091
      source "${candidate}/bin/activate"
    fi
    export PARCEL_SORTER_VENV="${candidate}"
    echo "Using Radeon Python environment: ${candidate}"
    return 0 2>/dev/null || exit 0
  fi
done

echo "ERROR: no Python environment with working ROCm PyTorch was found." >&2
echo "Set PARCEL_SORTER_VENV to the official cloud environment and retry." >&2
return 1 2>/dev/null || exit 1
