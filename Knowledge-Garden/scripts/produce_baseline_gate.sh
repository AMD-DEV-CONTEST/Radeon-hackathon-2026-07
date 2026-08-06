#!/bin/bash
# produce_baseline_gate.sh — write the versioned baseline-gate.json (Todo 11/F3).
# Recomputes schema_hash from canonical db/migrations/*.sql, probes endpoints with
# real curl, runs the web build check, and writes the gate atomically.
#
# Usage:
#   bash scripts/produce_baseline_gate.sh \
#       --db-schema-dir db/migrations --api http://127.0.0.1:8510 \
#       --model http://127.0.0.1:8001 --out <path>
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCHEMA_DIR=""
API_URL=""
MODEL_URL=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --db-schema-dir) SCHEMA_DIR="$2"; shift 2;;
    --api) API_URL="$2"; shift 2;;
    --model) MODEL_URL="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$SCHEMA_DIR" ] && [ -n "$API_URL" ] && [ -n "$MODEL_URL" ] && [ -n "$OUT" ] || {
  echo "produce_baseline_gate: all of --db-schema-dir --api --model --out required" >&2; exit 2; }

# schema hash (same canonicalization as validate_baseline_gate.py)
SHA="$(/opt/venv/bin/python - "$SCHEMA_DIR" <<'PY'
import hashlib, sys
from pathlib import Path
d = Path(sys.argv[1])
files = sorted((f for f in d.glob("*.sql") if not f.name.startswith("golden-")), key=lambda p: p.name.encode())
parts = []
for f in files:
    raw = f.read_bytes()
    text = raw.decode("utf-8").lstrip("\ufeff")
    lines = [ln.rstrip("\r").rstrip(" \t") for ln in text.split("\n")]
    parts.append("\n".join([l for l in lines if l]))
blob = "\n".join(parts) + "\n"
print(hashlib.sha256(blob.encode()).hexdigest())
PY
)"
[ -n "$SHA" ] || { echo "produce_baseline_gate: schema hash failed" >&2; exit 1; }

# endpoint health from real curl probes
probe() { curl -fsS --max-time 5 "$1/v1/models" >/dev/null 2>&1 && echo "ok" || echo "unreachable"; }
MODEL_H="$(curl -fsS --max-time 5 "$MODEL_URL/v1/models" >/dev/null 2>&1 && echo ok || echo unreachable)"
API_H="$(curl -fsS --max-time 5 "$API_URL/api/stats" >/dev/null 2>&1 && echo ok || echo unreachable)"

# web build ok
WEB_OK=false
if npm --prefix "$ROOT/web" run build >/dev/null 2>&1; then WEB_OK=true; fi

mkdir -p "$(dirname "$OUT")"
TMP="$OUT.tmp"
# shell booleans -> Python literals
if [ "$WEB_OK" = "true" ]; then PY_WEB_OK="True"; else PY_WEB_OK="False"; fi
/opt/venv/bin/python - "$TMP" <<PY
import json, sys, time
gate = {
    "baseline_schema_version": 1,
    "schema_hash": "$SHA",
    "endpoint_health": {"model_8001": "$MODEL_H", "api_8510": "$API_H"},
    "web_build_ok": $PY_WEB_OK,
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
json.dump(gate, open(sys.argv[1], "w"), indent=2)
PY
mv "$TMP" "$OUT"
echo "BASELINE_GATE_OK: $OUT schema_hash=$SHA model=$MODEL_H api=$API_H web=$WEB_OK"
exit 0
