#!/usr/bin/env bash
# Production smoke test for BotverseX — run on ECS or via SSH.
set -euo pipefail
BASE="${BASE_URL:-https://botversex.feispace.me}"
fail=0

check() {
  local name="$1" url="$2" expect="${3:-200}"
  local code
  code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 15 "$url" || echo "000")
  if [[ "$code" == "$expect" ]]; then
    echo "OK  $name ($code)"
  else
    echo "FAIL $name (got $code, want $expect)"
    fail=1
  fi
}

check_post() {
  local name="$1" url="$2" expect="${3:-200}"
  local code
  code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 15 -X POST "$url" \
    -H 'Content-Type: application/json' -d '{"page":"/robots"}' || echo "000")
  if [[ "$code" == "$expect" ]]; then
    echo "OK  $name ($code)"
  else
    echo "FAIL $name (got $code, want $expect)"
    fail=1
  fi
}

echo "=== BotverseX smoke: $BASE ==="
check "home" "$BASE/"
check "robots api" "$BASE/api/robots"
check "setup health" "$BASE/api/setup/health"
check "api health" "$BASE/health"
check "plans" "$BASE/api/v1/auth/plans"
check "register page" "$BASE/login"
check_post "copilot diagnose" "$BASE/api/v1/copilot/diagnose"

JS=$(curl -sk "$BASE/" | grep -oP 'index-[^"]+\.js' | head -1 || true)
if [[ -n "$JS" ]]; then
  check "js bundle" "$BASE/assets/$JS"
else
  echo "FAIL js bundle (not found in HTML)"
  fail=1
fi

exit "$fail"
