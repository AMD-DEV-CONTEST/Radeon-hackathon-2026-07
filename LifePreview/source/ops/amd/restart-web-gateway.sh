#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
SUPERVISOR_CONFIG="${2:-/persistent/douyin-amd/releases/current/deploy/amd/supervisord.conf}"

[[ -f "$ENV_FILE" ]] || { printf 'Missing environment file.\n' >&2; exit 1; }
[[ -f "$SUPERVISOR_CONFIG" ]] || { printf 'Missing Supervisor configuration.\n' >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${AMD_WEB_DIR:?AMD_WEB_DIR must be configured}"
[[ -f "$AMD_WEB_DIR/dist/index.html" ]] || {
  printf 'Missing built consumer Web entrypoint: %s\n' "$AMD_WEB_DIR/dist/index.html" >&2
  exit 1
}
[[ -f "$AMD_WEB_DIR/vite.config.ts" ]] || {
  printf 'Missing Vite gateway configuration: %s\n' "$AMD_WEB_DIR/vite.config.ts" >&2
  exit 1
}

curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:18082/health/ready >/dev/null

ctl=(supervisorctl -c "$SUPERVISOR_CONFIG")
if "${ctl[@]}" status web | grep -Eq '^web[[:space:]]+RUNNING'; then
  "${ctl[@]}" restart web
else
  "${ctl[@]}" start web
fi

for _attempt in {1..50}; do
  if curl --fail --silent --show-error --max-time 2 \
    http://127.0.0.1:14289/ >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:14289/ >/dev/null

probe_json_proxy() {
  local path="$1"
  local allowed_statuses="$2"
  local result status content_type
  result="$(curl --silent --show-error --max-time 10 --output /dev/null \
    --write-out '%{http_code} %{content_type}' "http://127.0.0.1:14289$path")"
  read -r status content_type <<<"$result"
  [[ "$status" =~ ^($allowed_statuses)$ ]] || {
    printf 'Unexpected status from gateway path %s: %s\n' "$path" "$status" >&2
    exit 1
  }
  [[ "$content_type" == application/json* ]] || {
    printf 'Gateway path %s did not return JSON: %s\n' "$path" "$content_type" >&2
    exit 1
  }
}

probe_json_proxy /api/books '200|401|403'
printf 'AMD Web gateway restarted and verified on 127.0.0.1:14289.\n'
