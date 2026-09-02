#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
SUPERVISOR_CONFIG="${2:-/persistent/douyin-amd/releases/current/deploy/amd/supervisord.conf}"

"$SCRIPT_DIR/preflight-radeon-cloud.sh" "$ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

mkdir -p "$AMD_ROOT/logs" "$AMD_ROOT/pids" "$AMD_ROOT/artifacts" "$AMD_ROOT/projects"

if [[ -S "$AMD_ROOT/pids/supervisor.sock" ]]; then
  supervisorctl -c "$SUPERVISOR_CONFIG" stop all || true
  supervisorctl -c "$SUPERVISOR_CONFIG" shutdown
  for _attempt in {1..50}; do
    [[ ! -S "$AMD_ROOT/pids/supervisor.sock" ]] && break
    sleep 0.1
  done
  [[ ! -S "$AMD_ROOT/pids/supervisor.sock" ]] || {
    printf 'Old Supervisor did not shut down.\n' >&2
    exit 1
  }
fi

(
  # Both Alembic configs use release-relative script_location values. Running
  # from an arbitrary SSH/Jupyter cwd resolves them outside the release.
  cd "$AMD_RELEASE_DIR/creative_hub"
  "$AMD_BIN/creative-hub-migrate"
  "$AMD_BIN/creative-orchestration-migrate"
)

supervisord -c "$SUPERVISOR_CONFIG"

ctl=(supervisorctl -c "$SUPERVISOR_CONFIG")
"${ctl[@]}" start search-mcp reader-mcp

"${ctl[@]}" start shidu-api
"${ctl[@]}" start research-worker factory-core vertical-slice-worker web
"$SCRIPT_DIR/smoke-radeon-cloud.sh" "$ENV_FILE"
printf 'AMD CPU services started; GPU/ComfyUI remain stopped until user click.\n'
