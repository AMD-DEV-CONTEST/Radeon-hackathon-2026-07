#!/usr/bin/env bash
set -euo pipefail

SETUP_STARTED_SECONDS=$SECONDS
RADEONNAV_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_SPEC=${PYTHON_SPEC:-3.12}
RADEONNAV_ENV=${RADEONNAV_ENV:-/opt/radeon-nav-venv}
UV_LINK_MODE=${UV_LINK_MODE:-hardlink}
PROJECT_ENV_LINK="$RADEONNAV_ROOT/UniLab/.venv"

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
  return 1
}

UV_COMMAND=$(find_uv) || {
  echo "uv was not found. Install it from https://docs.astral.sh/uv/ first." >&2
  exit 2
}

if [[ ! -e /dev/kfd ]]; then
  echo "warning: /dev/kfd is absent; ROCm GPU execution will not be available" >&2
fi
if [[ ! -e /dev/dri ]]; then
  echo "warning: /dev/dri is absent; headless MuJoCo EGL rendering may fail" >&2
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "warning: ffmpeg is absent; install it before recording videos" >&2
fi

without_proxy() {
  env \
    -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    "$@"
}

echo "[1/3] Syncing UniLab + NeuPAN with the ROCm 7.2 PyTorch index"
without_proxy env UV_PROJECT_ENVIRONMENT="$RADEONNAV_ENV" "$UV_COMMAND" sync \
  --project "$RADEONNAV_ROOT/UniLab" \
  --python "$PYTHON_SPEC" \
  --extra mujoco \
  --extra nrmp-rocm \
  --link-mode "$UV_LINK_MODE" \
  --frozen

echo "[2/3] Linking UniLab/.venv to the large-disk environment"
if [[ -L $PROJECT_ENV_LINK ]]; then
  ln -sfn "$RADEONNAV_ENV" "$PROJECT_ENV_LINK"
elif [[ -e $PROJECT_ENV_LINK ]]; then
  echo "$PROJECT_ENV_LINK exists and is not a symlink; move it aside first" >&2
  exit 2
else
  ln -s "$RADEONNAV_ENV" "$PROJECT_ENV_LINK"
fi

echo "[3/3] Verifying ROCm, MuJoCo, repositories, data, and weights"
MUJOCO_GL=${MUJOCO_GL:-egl} \
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$RADEONNAV_ROOT/UniLab/src:$RADEONNAV_ROOT/NeuPAN${PYTHONPATH:+:$PYTHONPATH}" \
  "$RADEONNAV_ENV/bin/python" \
  "$RADEONNAV_ROOT/setup/verify_environment.py"

echo "READY environment=$RADEONNAV_ENV elapsed_sec=$((SECONDS - SETUP_STARTED_SECONDS))"
