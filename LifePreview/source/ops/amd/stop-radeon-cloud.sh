#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
SUPERVISOR_CONFIG="${2:-/persistent/douyin-amd/releases/current/deploy/amd/supervisord.conf}"
[[ -f "$ENV_FILE" ]] || { printf 'Missing environment file.\n' >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -S "$AMD_ROOT/pids/supervisor.sock" ]]; then
  supervisorctl -c "$SUPERVISOR_CONFIG" stop all
  supervisorctl -c "$SUPERVISOR_CONFIG" shutdown
fi
printf 'AMD application services stopped; PostgreSQL and persisted data were retained.\n'
