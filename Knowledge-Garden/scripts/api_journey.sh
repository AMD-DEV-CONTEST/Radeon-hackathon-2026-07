#!/bin/bash
# api_journey.sh — Todo 8 happy-path disposable-stack journey (plan acceptance).
#
# 1. creates a verified backup via manage_learning_db.sh backup
# 2. writes a valid routing-decision.json stub
# 3. executes the GATED reset (both gates re-verified) -> PRAGMA integrity_check = ok
# 4. imports material, polls /api/extraction-runs/<id> until verified
# 5. starts learning, completes assessment
# 6. asserts a due review exists
# 7. drain -> undrain round trip, then a subsequent write succeeds
#
# Usage:
#   bash scripts/api_journey.sh [--port <p>] [--db <path>]
#   LC_API_PORT and LC_JOURNEY_DB env override the same.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${LC_API_PORT:-8512}"
DB="${LC_JOURNEY_DB:-/tmp/lc-t8-journey.sqlite}"
FIXTURE="${LC_JOURNEY_FIXTURE:-/tmp/lc-t8-fixture.json}"
BACKUP_LIST="/tmp/lc-t8-backup.txt"
ROUTING="$ROOT/docs/evaluation/routing-decision.json"
API_LOG="/tmp/lc-t8-api.log"
WORKDIR="${LC_JOURNEY_WORKDIR:-/tmp/lc-t8-journey}"
PYTHON="${LC_PYTHON:-/opt/venv/bin/python}"

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --db) DB="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

rm -rf "$WORKDIR" /tmp/lc-t8-*.json /tmp/lc-c*.body /tmp/lc-c*.code "$API_LOG"
mkdir -p "$WORKDIR"
export LC_DB_PATH="$DB"
export LC_DRAIN_STATE_FILE="$WORKDIR/drain.state.json"
export LC_DRAIN_LOCK_FILE="$WORKDIR/drain.lock"
export LC_WRITER_COUNT_FILE="$WORKDIR/writer_count.json"
export LC_MAINTENANCE_LOCK_FILE="$WORKDIR/maintenance.lock"
export LC_EXTRACT_STUB=verify

# ---------- 1. verified backup ----------
"$PYTHON" "$ROOT/scripts/bootstrap_study_fixture.py" --db "$DB" --out "$FIXTURE"
bash "$ROOT/scripts/manage_learning_db.sh" backup --db "$DB" --artifact-out "$BACKUP_LIST"
BACKUP="$(cat "$BACKUP_LIST")"
echo "[journey] backup=$BACKUP"

# ---------- 2. routing-decision stub (valid, recomputable) ----------
if [ ! -f "$ROUTING" ]; then
  "$PYTHON" "$ROOT/scripts/make_stub_report.py" --model "Qwen2.5-32B-AWQ" --out "$WORKDIR/qwen25.raw.json" \
    --support 78.0 --unsupported 15.0 --coverage 62.0 --agreement 88.0
  "$PYTHON" "$ROOT/scripts/make_stub_report.py" --model "Qwen3-32B-AWQ" --out "$WORKDIR/qwen3.raw.json" \
    --support 84.0 --unsupported 9.0 --coverage 71.0 --agreement 92.0
  "$PYTHON" "$ROOT/scripts/decide_routing.py" \
    --qwen25-report "$WORKDIR/qwen25.raw.json" --qwen3-report "$WORKDIR/qwen3.raw.json" \
    --schema "$ROOT/docs/routing-decision.schema.json" --out "$ROUTING"
fi
"$PYTHON" "$ROOT/scripts/validate_routing_decision.py" "$ROUTING" >/dev/null || { echo "[journey] routing stub invalid" >&2; exit 1; }

# ---------- 3. gated reset ----------
bash "$ROOT/scripts/manage_learning_db.sh" reset --backup "$BACKUP" --routing "$ROUTING" \
  || { echo "[journey] gated reset FAILED" >&2; exit 1; }
test "$(sqlite3 "$DB" "PRAGMA integrity_check")" = "ok" || { echo "[journey] integrity after reset != ok" >&2; exit 1; }
echo "[journey] gated reset ok, integrity ok"

# ---------- 3.5 seed a skill in the freshly reset DB (direct insert; material
#               import below creates verified units through the extraction pipeline) ----------
SKILL=$(sqlite3 "$DB" "INSERT INTO skills(name, description, created_at, updated_at) VALUES('旅程技能','','',''); SELECT last_insert_rowid();")
echo "[journey] seeded skill_id=$SKILL after reset"

# ---------- API up ----------
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > "$API_LOG" 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT
for i in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/api/stats" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/api/stats" >/dev/null || { echo "[journey] API never ready" >&2; tail -5 "$API_LOG" >&2; exit 1; }

# ---------- 4. material import + poll extraction to verified ----------
RESP=$(curl -sS -X POST "http://127.0.0.1:$PORT/api/materials" -H 'Content-Type: application/json' \
  -d "{\"skill_id\":$SKILL,\"text\":\"Raft 通过强领导者简化共识协议。领导者选举使用随机超时选举，多数票胜出。日志复制由领导者发起，多数确认后提交。\"}")
RUN_ID=$(echo "$RESP" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin)["run_id"])')
echo "[journey] material imported run_id=$RUN_ID"
STATUS="queued"
for i in $(seq 1 60); do
  STATUS=$(curl -sS "http://127.0.0.1:$PORT/api/extraction-runs/$RUN_ID" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin)["status"])')
  [ "$STATUS" = "verified" ] && break
  [ "$STATUS" = "failed" ] && { echo "[journey] extraction FAILED" >&2; curl -sS "http://127.0.0.1:$PORT/api/extraction-runs/$RUN_ID" >&2; exit 1; }
  sleep 1
done
test "$STATUS" = "verified" || { echo "[journey] extraction did not verify: $STATUS" >&2; exit 1; }
UNIT_ID=$(sqlite3 "$DB" "SELECT id FROM learning_units WHERE skill_id=$SKILL AND status='verified' LIMIT 1")
echo "[journey] extraction verified unit_id=$UNIT_ID"

# ---------- 5. learning + assessment ----------
SID=$(curl -sS -X POST "http://127.0.0.1:$PORT/api/learning-sessions" -H 'Content-Type: application/json' \
  -d "{\"skill_id\":$SKILL}" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin)["session"]["id"])')
GOLD=$("$PYTHON" -c 'import json; print(json.load(open("'$FIXTURE'"))["gold_recall_text"])')
curl -sS -X POST "http://127.0.0.1:$PORT/api/assessment" -H 'Content-Type: application/json' \
  -d "{\"session_id\":$SID,\"unit_id\":$UNIT_ID,\"idempotency_key\":\"j1\",\"recall\":\"$GOLD\"}" >/dev/null

# ---------- 6. due review exists ----------
test "$(sqlite3 "$DB" "SELECT COUNT(*) FROM learning_progress WHERE next_review_at IS NOT NULL")" = 1 \
  || { echo "[journey] no due review after assessment" >&2; exit 1; }
echo "[journey] due review scheduled"

# ---------- 7. drain -> undrain round trip, then write succeeds ----------
DRAIN_STATE=$(curl -sS -X POST "http://127.0.0.1:$PORT/api/admin/drain" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin)["state"])')
test "$DRAIN_STATE" = "drained" || { echo "[journey] drain != drained: $DRAIN_STATE" >&2; exit 1; }
UNDRAIN_STATE=$(curl -sS -X POST "http://127.0.0.1:$PORT/api/admin/undrain" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin)["state"])')
test "$UNDRAIN_STATE" = "accepting" || { echo "[journey] undrain != accepting: $UNDRAIN_STATE" >&2; exit 1; }
# subsequent write succeeds
WRITE_CODE=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/api/materials" \
  -H 'Content-Type: application/json' \
  -d "{\"skill_id\":$SKILL,\"text\":\"二次写入验证：drain 往返后数据库可继续接收材料。\"}")
test "$WRITE_CODE" = "200" || { echo "[journey] write after undrain failed: $WRITE_CODE" >&2; exit 1; }
echo "[journey] drain->undrain round trip ok, write admitted"

kill $API_PID 2>/dev/null || true; wait $API_PID 2>/dev/null || true
trap - EXIT
echo "API_JOURNEY_OK: backup -> gated reset -> extraction -> learning -> assessment -> due review -> drain/undrain"
exit 0
