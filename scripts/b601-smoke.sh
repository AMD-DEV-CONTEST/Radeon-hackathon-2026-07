#!/usr/bin/env bash
# M27 B601 acceptance smoke — requires Local Agent on :8002 and hardware optional.
set -euo pipefail
BASE="${B601_SMOKE_BASE:-http://127.0.0.1:8002}"

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[OK] $*"; }

curl -fsS "$BASE/api/b601/health" >/dev/null || fail "health unreachable at $BASE"
ok "health"

curl -fsS "$BASE/api/b601/urdf/health" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('ok'), d
print('meshes', d['mesh_present'], '/', d['mesh_total'])
" || fail "urdf health"
ok "urdf meshes"

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/urdf/b601_rs/b601_rs.urdf")
[[ "$code" == "200" ]] || fail "urdf 200 got $code"
ok "urdf file"

curl -fsS -X POST "$BASE/api/b601/can/up" >/dev/null 2>&1 && ok "can/up" || echo "[SKIP] can/up (no sudo/CAN)"

curl -fsS -X POST "$BASE/api/b601/recover" >/dev/null 2>&1 && ok "recover" || echo "[SKIP] recover (no hardware)"

curl -fsS -X POST "$BASE/api/b601/teleop/start" \
  -H 'Content-Type: application/json' \
  -d '{"use_cameras":false,"restart":true}' >/dev/null 2>&1 && ok "teleop start" || echo "[SKIP] teleop start"

sleep 2
curl -fsS -X POST "$BASE/api/b601/teleop/stop" >/dev/null 2>&1 && ok "teleop stop" || echo "[SKIP] teleop stop"

curl -fsS -X POST "$BASE/api/b601/disable" >/dev/null 2>&1 && ok "disable" || echo "[SKIP] disable"

echo "[b601-smoke] finished"
