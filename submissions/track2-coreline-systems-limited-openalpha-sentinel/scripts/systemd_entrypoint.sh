#!/usr/bin/env bash
set -euo pipefail

SYSTEM_ENV_FILE="${OPENALPHA_SYSTEM_ENV_FILE:-/etc/openalpha-sentinel.env}"
if [[ -r "$SYSTEM_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SYSTEM_ENV_FILE"
  set +a
fi

: "${OPENALPHA_ROOT:?OPENALPHA_ROOT must be set in $SYSTEM_ENV_FILE}"
if [[ ! -d "$OPENALPHA_ROOT" ]]; then
  echo "OPENALPHA_ROOT does not exist: $OPENALPHA_ROOT" >&2
  exit 1
fi
cd "$OPENALPHA_ROOT"

case "${1:-}" in
  api)
    exec "$OPENALPHA_ROOT/.venv/bin/openalpha" serve
    ;;
  worker)
    exec "$OPENALPHA_ROOT/.venv/bin/openalpha" worker
    ;;
  llama)
    exec "$OPENALPHA_ROOT/scripts/start_rocm_llama.sh"
    ;;
  *)
    echo "Usage: $0 api|worker|llama" >&2
    exit 2
    ;;
esac
