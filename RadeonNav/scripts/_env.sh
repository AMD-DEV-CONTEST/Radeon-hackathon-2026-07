#!/usr/bin/env bash
set -euo pipefail

RADEONNAV_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

find_uv() {
  if [[ -n ${UV_BIN:-} ]] && command -v "$UV_BIN" >/dev/null 2>&1; then
    command -v "$UV_BIN"
    return
  fi
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return
  fi
  if [[ -x /opt/venv/bin/uv ]]; then
    printf '%s\n' /opt/venv/bin/uv
    return
  fi
  echo "uv was not found; set UV_BIN or run setup/setup_rocm.sh" >&2
  return 1
}

UV_COMMAND=$(find_uv)
if [[ ! -x "$RADEONNAV_ROOT/UniLab/.venv/bin/python" && -z ${UV_PROJECT_ENVIRONMENT:-} ]]; then
  echo "UniLab/.venv is not ready; run setup/setup_rocm.sh first" >&2
  exit 2
fi
export MUJOCO_GL=${MUJOCO_GL:-egl}
export HIP_VISIBLE_DEVICES=${HIP_VISIBLE_DEVICES:-0}
export ROCR_VISIBLE_DEVICES=${ROCR_VISIBLE_DEVICES:-$HIP_VISIBLE_DEVICES}
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-$HIP_VISIBLE_DEVICES}
export PYTHONDONTWRITEBYTECODE=${PYTHONDONTWRITEBYTECODE:-1}
export PYTHONPATH="$RADEONNAV_ROOT/UniLab/src:$RADEONNAV_ROOT/NeuPAN${PYTHONPATH:+:$PYTHONPATH}"

run_python() {
  "$UV_COMMAND" run --project "$RADEONNAV_ROOT/UniLab" --no-sync python "$@"
}
