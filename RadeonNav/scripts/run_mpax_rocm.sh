#!/usr/bin/env bash
set -euo pipefail

RADEONNAV_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ROCM_ROOT=${ROCM_ROOT:-/opt/rocm}
SYSTEM_HIP_RUNTIME="$ROCM_ROOT/lib/libamdhip64.so.7"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 PYTHON_SCRIPT [arguments ...]" >&2
  exit 2
fi
if [[ ! -e "$SYSTEM_HIP_RUNTIME" ]]; then
  echo "ROCm HIP runtime was not found: $SYSTEM_HIP_RUNTIME" >&2
  exit 2
fi

export RADEONNAV_MPAX_ROCM=1
export LD_PRELOAD="$SYSTEM_HIP_RUNTIME${LD_PRELOAD:+:$LD_PRELOAD}"
export LLVM_PATH=${LLVM_PATH:-$ROCM_ROOT/llvm}
export XLA_PYTHON_CLIENT_PREALLOCATE=${XLA_PYTHON_CLIENT_PREALLOCATE:-false}
export JAX_ENABLE_X64=${JAX_ENABLE_X64:-true}

exec "$RADEONNAV_ROOT/scripts/run_python.sh" "$@"
