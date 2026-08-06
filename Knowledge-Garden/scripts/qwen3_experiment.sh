#!/bin/bash
# qwen3_experiment.sh — reversible Qwen3 checkpoint download + sequential serving experiment controller.
#
# Commands:
#   qwen3_experiment.sh preflight                       # disk/VRAM checks only
#   qwen3_experiment.sh run --dry-run                   # validate args, make no process changes
#   qwen3_experiment.sh run --model-port <p>            # stop captured service on <p>, launch Qwen3, run, restore
#       [--model-dir <path>] [--served-name <name>] [--health-timeout <s>] [--descriptor-out <path>]
#
# Guarantees:
#   - Captures a VERSIONED descriptor of the service on --model-port BEFORE any stop.
#   - Refuses to stop anything unless the descriptor validates against docs/service-descriptor.schema.json.
#   - EXIT trap (success/signal/failure) restores the captured service and compares identity.
set -uo pipefail

MODEL_DIR_DEFAULT="/persistent/models/Qwen3-32B-AWQ"
MODEL_SERVED_DEFAULT="Qwen3-32B-AWQ"
SCHEMA="/persistent/learning-companion/docs/service-descriptor.schema.json"
EXPERIMENT_DIR="${LC_EXPERIMENT_DIR:-/tmp/lc-experiment}"
REQUIRED_DISK_GB=24
REQUIRED_VRAM_GB=12

cmd="${1:-help}"
shift || true

case "$cmd" in
  preflight)
    # disk
    AVAIL_KB="$(df -Pk /persistent 2>/dev/null | awk 'NR==2{print $4}')"
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    if [ "$AVAIL_GB" -lt "$REQUIRED_DISK_GB" ]; then
      echo "PREFLIGHT_FAIL: disk ${AVAIL_GB}GB < required ${REQUIRED_DISK_GB}GB" >&2; exit 1
    fi
    # VRAM (rocm-smi if available)
    if command -v rocm-smi >/dev/null 2>&1; then
      USED_B="$(rocm-smi --showmeminfo vram 2>/dev/null | grep 'VRAM Total Used Memory' | grep -oP '\d+' | head -1)"
      TOTAL_B="$(rocm-smi --showmeminfo vram 2>/dev/null | grep 'VRAM Total Memory' | grep -oP '\d+' | head -1)"
      if [ -n "$USED_B" ] && [ -n "$TOTAL_B" ]; then
        FREE_GB=$(( (TOTAL_B - USED_B) / 1024 / 1024 / 1024 ))
        if [ "$FREE_GB" -lt "$REQUIRED_VRAM_GB" ]; then
          echo "PREFLIGHT_FAIL: free VRAM ${FREE_GB}GB < required ${REQUIRED_VRAM_GB}GB" >&2; exit 1
        fi
        echo "PREFLIGHT_OK: disk_avail=${AVAIL_GB}GB vram_free=${FREE_GB}GB"
      else
        echo "PREFLIGHT_OK: disk_avail=${AVAIL_GB}GB vram=unknown"
      fi
    else
      echo "PREFLIGHT_OK: disk_avail=${AVAIL_GB}GB vram=rocm-smi-unavailable"
    fi
    exit 0
    ;;
  run)
    ;;
  help|*)
    sed -n '2,20p' "$0"; exit 0
    ;;
esac

DRY_RUN=0
MODEL_PORT=""
MODEL_DIR="$MODEL_DIR_DEFAULT"
SERVED_NAME="$MODEL_SERVED_DEFAULT"
HEALTH_TIMEOUT=180
DESCRIPTOR_OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift;;
    --model-port) MODEL_PORT="$2"; shift 2;;
    --model-dir) MODEL_DIR="$2"; shift 2;;
    --served-name) SERVED_NAME="$2"; shift 2;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2;;
    --descriptor-out) DESCRIPTOR_OUT="$2"; shift 2;;
    *) echo "unknown run arg: $1" >&2; exit 2;;
  esac
done

[ -n "$MODEL_PORT" ] || { echo "qwen3_experiment run: --model-port required" >&2; exit 2; }
mkdir -p "$EXPERIMENT_DIR"

if [ "$DRY_RUN" = 1 ]; then
  # validate args + schema readability; make NO process changes
  [ -f "$SCHEMA" ] || { echo "DRYRUN_FAIL: schema missing $SCHEMA" >&2; exit 1; }
  [ -d "$MODEL_DIR" ] || echo "DRYRUN_WARN: model dir $MODEL_DIR missing (download required)" >&2
  python3 -c 'import json; json.load(open("'$SCHEMA'"))' || { echo "DRYRUN_FAIL: invalid schema JSON" >&2; exit 1; }
  echo "DRYRUN_OK: no process changes made"
  exit 0
fi

[ -d "$MODEL_DIR" ] || { echo "run: model dir $MODEL_DIR missing; download Qwen/Qwen3-32B-AWQ first" >&2; exit 1; }

# ---- capture incumbent descriptor BEFORE any stop ----
CAPTURE="${EXPERIMENT_DIR}/incumbent-descriptor.json"
if bash /persistent/learning-companion/scripts/capture_service_descriptor.sh \
    --model-port "$MODEL_PORT" --served-name "$(curl -fsS --max-time 5 "http://127.0.0.1:${MODEL_PORT}/v1/models" 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null || echo unknown)" \
    --out "$CAPTURE" 2>/dev/null; then
  echo "[qwen3] captured incumbent descriptor -> $CAPTURE"
else
  echo "run: no incumbent service on :$MODEL_PORT; nothing to restore (will still test launch)" >&2
  CAPTURE=""
fi

# ---- validate descriptor against schema (refuse to stop on failure) ----
if [ -n "$CAPTURE" ] && [ -f "$CAPTURE" ]; then
  /opt/venv/bin/python - "$CAPTURE" "$SCHEMA" <<'PY' || { echo "run: incumbent descriptor FAILED schema validation — refusing to stop anything" >&2; exit 1; }
import json, sys
desc = json.load(open(sys.argv[1]))
schema = json.load(open(sys.argv[2]))
from jsonschema import validate as _v
try:
    import jsonschema
    jsonschema.validate(desc, schema)
except ImportError:
    # minimal structural check without dependency
    for f in ["descriptor_schema_version","executable","argv","cwd","checkpoint_path","checkpoint_revision","env","port","served_model_id","log_path","launcher_method","captured_at"]:
        assert f in desc, f"missing {f}"
    assert desc["descriptor_schema_version"] == 1
print("descriptor schema validation OK")
PY
  echo "[qwen3] descriptor validated"
fi

# ---- EXIT trap: restore captured service on any exit path ----
restore() {
  local rc=$?
  if [ -n "$CAPTURE" ] && [ -f "$CAPTURE" ]; then
    echo "[qwen3] EXIT trap restoring captured service (rc=$rc)..."
    # stop Qwen3 on the port if still running
    pkill -f "openai.api_serve[r].*--port $MODEL_PORT" 2>/dev/null || true
    sleep 2
    # restore via start_vllm.sh using descriptor fields
    CP="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkpoint_path"])' "$CAPTURE" 2>/dev/null || true)"
    SN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["served_model_id"])' "$CAPTURE" 2>/dev/null || true)"
    if [ -n "$CP" ] && [ -n "$SN" ] && [ -d "$CP" ]; then
      bash /persistent/learning-companion/scripts/start_incumbent_model.sh \
        --model-port "$MODEL_PORT" --served-name "$SN" --health-timeout 180 >/tmp/lc-restore.log 2>&1
      bash /persistent/learning-companion/scripts/verify_restoration.sh --port "$MODEL_PORT" --descriptor "$CAPTURE" \
        && echo "[qwen3] RESTORE_OK" || echo "[qwen3] RESTORE_IDENTITY_MISMATCH" >&2
    else
      echo "[qwen3] RESTORE_SKIP: cannot reconstruct descriptor" >&2
    fi
  else
    echo "[qwen3] no captured service to restore" >&2
  fi
  return $rc
}
trap restore EXIT INT TERM

# ---- launch Qwen3 on the port ----
echo "[qwen3] launching $SERVED_NAME from $MODEL_DIR on :$MODEL_PORT"
LOG="${EXPERIMENT_DIR}/qwen3_${MODEL_PORT}.log"
setsid env \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_ENDPOINT=https://hf-mirror.com VLLM_ATTENTION_BACKEND=ROCM_ATTN \
  /opt/venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_DIR" \
    --served-model-name "$SERVED_NAME" \
    --host 0.0.0.0 --port "$MODEL_PORT" \
    --max-model-len 4096 --gpu-memory-utilization 0.5 --enforce-eager \
    --enable-auto-tool-choice --tool-call-parser hermes \
  > "$LOG" 2>&1 < /dev/null &

for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  curl -fsS --max-time 5 "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS --max-time 5 "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null 2>&1 || { echo "Qwen3_LAUNCH_FAIL: $LOG" >&2; exit 1; }

# write experiment descriptor (the Qwen3 descriptor for later identity compare)
DESC_OUT="${DESCRIPTOR_OUT:-${EXPERIMENT_DIR}/experiment.json}"
bash /persistent/learning-companion/scripts/capture_service_descriptor.sh \
  --model-port "$MODEL_PORT" --served-name "$SERVED_NAME" --out "$DESC_OUT" || true

echo "QWEN3_RUN_OK: $SERVED_NAME serving on :$MODEL_PORT (log: $LOG)"
exit 0
