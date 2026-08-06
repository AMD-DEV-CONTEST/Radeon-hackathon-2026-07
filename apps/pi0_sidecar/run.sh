#!/usr/bin/env bash
# Run the Pi0 sidecar on 127.0.0.1:8010.
#
# Safe to run alongside apps/realtime on 8002 — they share nothing except
# the workspace filesystem. Environment is intentionally stripped of the
# ROCm LD_PRELOAD so the 3.12 venv stays self-contained.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HERE}/.venv"

if [ ! -x "${VENV}/bin/python" ]; then
  echo "ERROR: venv missing at ${VENV}. Run: bash ${HERE}/setup_env.sh" >&2
  exit 1
fi

unset LD_PRELOAD
# Avoid inheriting desktop/system proxy settings in local sidecar mode.
# Otherwise HF Hub/httpx may try SOCKS transport and fail if extras differ.
unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONUNBUFFERED=1
export HF_HUB_ENABLE_HF_TRANSFER=${HF_HUB_ENABLE_HF_TRANSFER:-0}

HOST="${PI0_SIDECAR_HOST:-127.0.0.1}"
PORT="${PI0_SIDECAR_PORT:-8010}"

echo "[pi0_sidecar] starting uvicorn on ${HOST}:${PORT}"
exec "${VENV}/bin/python" -m uvicorn server:app \
  --app-dir "${HERE}" \
  --host "${HOST}" --port "${PORT}" \
  --workers 1 --log-level info
