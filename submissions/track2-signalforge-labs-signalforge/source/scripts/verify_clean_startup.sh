#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

tmp_dir="$(mktemp -d)"
port="${SIGNALFORGE_CLEAN_STARTUP_PORT:-$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')}"
pid=""
cleanup() {
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

go build -trimpath -o "$tmp_dir/signalforge-workspace" ./cmd/signalforge-workspace
if [[ ! -f web/dist/index.html ]]; then
  npm --prefix web ci --no-audit --no-fund
  npm --prefix web run build
fi
started_ns="$(python3 -c 'import time; print(time.monotonic_ns())')"
env -i \
  HOME="$tmp_dir/home" \
  PATH="$PATH" \
  "$tmp_dir/signalforge-workspace" \
    --mode fixture \
    --listen "127.0.0.1:$port" \
    --disable-case-store \
    --event-delay 0 \
    --static-dir web/dist \
    >"$tmp_dir/stdout.log" 2>"$tmp_dir/stderr.log" &
pid="$!"

ready=0
for _ in $(seq 1 100); do
  if curl --silent --show-error --fail "http://127.0.0.1:$port/api/v1/health" \
    >"$tmp_dir/health.json" 2>/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    cat "$tmp_dir/stderr.log" >&2
    exit 1
  fi
  sleep 0.05
done
if [[ "$ready" -ne 1 ]]; then
  echo "clean fixture startup did not become ready" >&2
  cat "$tmp_dir/stderr.log" >&2
  exit 1
fi

ready_ns="$(python3 -c 'import time; print(time.monotonic_ns())')"
startup_ms="$(( (ready_ns - started_ns) / 1000000 ))"
jq -e '.status == "ok" and .local_only == true and .mode == "fixture"' \
  "$tmp_dir/health.json" >/dev/null
curl --silent --show-error --fail "http://127.0.0.1:$port/api/v1/config" \
  | jq -e '.local_only == true and .endpoint_scope == "loopback_only" and .retention_default == false' \
  >/dev/null
curl --silent --show-error --fail "http://127.0.0.1:$port/api/v1/cases/golden" \
  | jq -e '.status == "completed" and .execution.local_only == true' >/dev/null
curl --silent --show-error --fail "http://127.0.0.1:$port/" \
  | grep -q '<div id="root"></div>'

if [[ "$startup_ms" -ge 5000 ]]; then
  echo "clean fixture startup exceeded 5 seconds: ${startup_ms}ms" >&2
  exit 1
fi
printf 'clean fixture startup passed in %sms\n' "$startup_ms"
