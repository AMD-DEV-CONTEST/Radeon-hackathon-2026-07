#!/bin/bash
# capture_service_descriptor.sh — capture a managed-service descriptor for a running vLLM service.
# Usage:
#   bash scripts/capture_service_descriptor.sh --model-port <port> --served-name <name> --out <path>
set -u

PORT=""
SERVED=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --model-port) PORT="$2"; shift 2;;
    --served-name) SERVED="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$PORT" ] || { echo "capture: --model-port required" >&2; exit 2; }
[ -n "$SERVED" ] || { echo "capture: --served-name required" >&2; exit 2; }
[ -n "$OUT" ] || { echo "capture: --out required" >&2; exit 2; }

PID="$(bash /persistent/learning-companion/scripts/find_listener_pid.sh "$PORT" 2>/dev/null || true)"
[ -n "$PID" ] || PID="$(ss -ltnp "sport = :${PORT}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)"
[ -n "$PID" ] || PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1)"
[ -n "$PID" ] || { echo "capture: no listener PID on :${PORT}" >&2; exit 1; }

EXEC="$(readlink -f "/proc/${PID}/exe" 2>/dev/null)"
CWD="$(readlink -f "/proc/${PID}/cwd" 2>/dev/null)"
ARGV="$(tr '\0' '\n' < "/proc/${PID}/cmdline" 2>/dev/null | python3 -c 'import sys,json; print(json.dumps([l for l in sys.stdin.read().split("\n") if l]))')"
ENV="$(tr '\0' '\n' < "/proc/${PID}/environ" 2>/dev/null | grep -E '^(HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE|HF_ENDPOINT|VLLM_ATTENTION_BACKEND|FT_DIALOGUE_URL|FT_BATCH_URL|LC_DB_PATH|LC_GRADER_STUB)=' | python3 -c 'import sys,json; d={}
for l in sys.stdin.read().split("\n"):
    if "=" in l:
        k,v=l.split("=",1); d[k]=v
print(json.dumps(d))')"

# checkpoint path from argv: the token after --model
CP=""
prev=""
for tok in $(echo "$ARGV" | python3 -c 'import sys,json; print(" ".join(json.load(sys.stdin)))'); do
  if [ "$prev" = "--model" ]; then CP="$tok"; break; fi
  prev="$tok"
done
[ -n "$CP" ] || CP="$(echo "$ARGV" | python3 -c 'import sys,json; a=json.load(sys.stdin); print(a[-1] if a else "")')"
[ -n "$CP" ] && [ -d "$CP" ] || { echo "capture: cannot determine checkpoint dir" >&2; exit 1; }

# independent revision: model-manifest.json revision, else config.json+safetensors index hash
REV=""
if [ -f "$CP/model-manifest.json" ]; then
  REV="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("revision",""))' "$CP/model-manifest.json" 2>/dev/null || true)"
fi
if [ -z "$REV" ] && [ -f "$CP/config.json" ]; then
  REV="$(sha256sum "$CP/config.json" "$CP"/model.safetensors.index.json 2>/dev/null | sha256sum | cut -d' ' -f1)"
fi
[ -n "$REV" ] || { echo "capture: cannot compute checkpoint revision" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
python3 - "$OUT" <<PY
import json, sys, time
out = sys.argv[1]
desc = {
  "descriptor_schema_version": 1,
  "executable": "$EXEC",
  "argv": $ARGV,
  "cwd": "$CWD",
  "checkpoint_path": "$CP",
  "checkpoint_revision": "$REV",
  "env": $ENV,
  "port": $PORT,
  "served_model_id": "$SERVED",
  "log_path": "/persistent/models/vllm_${PORT}.log",
  "launcher_method": "manual",
  "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
}
json.dump(desc, open(out, "w"), ensure_ascii=False, indent=2)
print("CAPTURE_OK: port=$PORT model=$SERVED pid=$PID -> $OUT")
PY
exit $?
