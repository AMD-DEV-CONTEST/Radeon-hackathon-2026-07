#!/usr/bin/env bash
# Shared helpers for project shell scripts. Source this file; do not execute it.

set -euo pipefail

# Project root (parent of scripts/)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Optional conda env (local dev machine)
if [[ -z "${PYTHON:-}" ]]; then
  if command -v conda >/dev/null 2>&1 && conda env list 2>/dev/null | grep -qE '^radeonvla-dev\s'; then
    PYTHON=(conda run -n radeonvla-dev --no-capture-output python)
  else
    PYTHON=(python)
  fi
else
  # shellcheck disable=SC2206
  PYTHON=($PYTHON)
fi

log()  { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
ok()   { printf '[%s] OK  %s\n' "$(date '+%H:%M:%S')" "$*"; }
die()  { printf '[%s] ERR %s\n' "$(date '+%H:%M:%S')" "$*" >&2; exit 1; }

run() {
  log "\$ $*"
  "$@"
}

run_py() {
  log "\$ ${PYTHON[*]} $*"
  "${PYTHON[@]}" "$@"
}

section() {
  echo
  echo "======== $* ========"
}

elapsed() {
  local start=$1
  local end
  end=$(date +%s)
  echo $((end - start))
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

# Load .env if present (KEY=VALUE lines; comments allowed)
load_dotenv() {
  local env_file="${1:-$ROOT/.env}"
  if [[ -f "$env_file" ]]; then
    log "Loading $env_file"
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

# LeRobot 0.6 writes numbered checkpoint directories (for example 010000)
# instead of always creating checkpoints/last. Prefer the compatibility link
# when present, otherwise select the numerically latest pretrained model.
latest_pretrained_model() {
  local train_dir=$1
  local legacy="$train_dir/checkpoints/last/pretrained_model"
  local latest

  if [[ -d "$legacy" ]]; then
    printf '%s\n' "$legacy"
    return 0
  fi

  latest=$(find "$train_dir/checkpoints" -mindepth 2 -maxdepth 2 \
    -type d -name pretrained_model -print 2>/dev/null | sort -V | tail -n 1)
  [[ -n "$latest" ]] || return 1
  printf '%s\n' "$latest"
}
