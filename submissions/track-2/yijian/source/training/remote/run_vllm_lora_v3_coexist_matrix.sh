#!/usr/bin/env bash
# Formal 0.72/0.75/0.78 W7900 coexistence matrix for frozen YIJIAN LoRA v3.
set -u -o pipefail

VLLM=/workspace/yijian/vllm-venv/bin/vllm
PYTHON=/workspace/yijian-venv/bin/python
BASE=/workspace/yijian/qwen3-14b-bf16
ADAPTER=/persistent/yijian/models/yijian-lora-v3-frozen/adapter
ALIAS=YIJIAN-Qwen3-14B-LoRA-gold-runtime-v3-BF16
KATAGO=/persistent/yijian/katago-v1.16.5/build/katago
KATAGO_MODEL=/persistent/yijian/katago-models/kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz
KATAGO_CONFIG=/persistent/yijian/project/gomentor/deploy/cloud/katago_analysis_w7900.cfg
STRESS=/workspace/yijian/vllm-lora-v3-matrix/stress_qwen3_katago_coexist.py
OUT=/workspace/yijian/vllm-lora-v3-matrix/results
PID_FILE=/workspace/yijian/vllm-lora-v3-matrix/vllm.pid
RESTORE_14B=/workspace/yijian/lora-runtime-v3-lr3e5/bin/start_lora14b_v3_fast_preview.sh
RESTORE_27B=/workspace/yijian/lora-gold-v2/bin/restore_27b.sh
UTILIZATIONS=(0.72 0.75 0.78)

for path in "$VLLM" "$PYTHON" "$BASE/config.json" "$ADAPTER/adapter_config.json" \
  "$KATAGO" "$KATAGO_MODEL" "$KATAGO_CONFIG" "$STRESS"; do
  [[ -e "$path" ]] || { echo "missing matrix input: $path" >&2; exit 2; }
done
mkdir -p "$OUT"

stop_vllm() {
  mapfile -t pids < <(pgrep -f 'vllm.*serve.*/workspace/yijian/qwen3-14b-bf16' || true)
  if ((${#pids[@]})); then
    kill "${pids[@]}" || true
  fi
  for _ in $(seq 1 90); do
    pgrep -f 'vllm.*serve.*/workspace/yijian/qwen3-14b-bf16' >/dev/null || return 0
    sleep 1
  done
  echo "vLLM did not stop within 90 seconds" >&2
  return 1
}

stop_llama_port() {
  local port="$1"
  mapfile -t pids < <(pgrep -f "llama-server.*--port $port" || true)
  if ((${#pids[@]})); then
    kill "${pids[@]}" || true
  fi
  for _ in $(seq 1 60); do
    pgrep -f "llama-server.*--port $port" >/dev/null || return 0
    sleep 1
  done
  echo "llama-server on port $port did not stop" >&2
  return 1
}

restore_services() {
  stop_vllm || true
  "$RESTORE_14B" > /workspace/yijian/vllm-lora-v3-matrix/restore-14b.log 2>&1 || true
  "$RESTORE_27B" > /workspace/yijian/vllm-lora-v3-matrix/restore-27b.log 2>&1 || true
}
trap restore_services EXIT

start_profile() {
  local utilization="$1"
  local log="$OUT/util-$utilization-vllm.log"
  stop_vllm || return 1
  stop_llama_port 8082 || return 1
  stop_llama_port 8083 || return 1
  export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 VLLM_PLUGINS=""
  nohup "$VLLM" serve "$BASE" \
    --served-model-name Qwen3-14B \
    --host 127.0.0.1 --port 8083 \
    --dtype bfloat16 --max-model-len 8192 --max-num-seqs 2 \
    --gpu-memory-utilization "$utilization" --enable-prefix-caching \
    --enable-lora --max-lora-rank 16 \
    --lora-modules "$ALIAS=$ADAPTER" \
    >"$log" 2>&1 &
  echo $! >"$PID_FILE"
  for _ in $(seq 1 300); do
    if curl -fsS --max-time 3 http://127.0.0.1:8083/v1/models 2>/dev/null | grep -Fq "$ALIAS"; then
      return 0
    fi
    pid="$(tr -dc '0-9' < "$PID_FILE")"
    [[ -n "$pid" && -d "/proc/$pid" ]] || break
    sleep 1
  done
  tail -120 "$log" >&2 || true
  return 1
}

passed=()
failed=()
for utilization in "${UTILIZATIONS[@]}"; do
  echo "=== YIJIAN LoRA v3 BF16 utilization=$utilization ==="
  report="$OUT/util-$utilization.json"
  log="$OUT/util-$utilization-vllm.log"
  if start_profile "$utilization" && \
    YIJIAN_VLLM_GPU_MEMORY_UTILIZATION="$utilization" \
      "$PYTHON" "$STRESS" \
        --katago "$KATAGO" --katago-model "$KATAGO_MODEL" \
        --katago-config "$KATAGO_CONFIG" \
        --llm-url http://127.0.0.1:8083/v1 --llm-model "$ALIAS" \
        --cycles 30 --p95-limit 12 --timeout 180 \
        --vllm-log "$log" --output "$report"; then
    passed+=("$utilization")
  else
    failed+=("$utilization")
  fi
done

stop_vllm || true
"$PYTHON" - "$OUT/summary.json" "${passed[*]}" "${failed[*]}" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
output = Path(sys.argv[1])
passed, failed = sys.argv[2].split(), sys.argv[3].split()
reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(output.parent.glob("util-*.json"))]
value = {
    "schemaVersion": "yijian-w7900-vllm-lora-v3-coexist-matrix-v1",
    "createdAt": datetime.now(timezone.utc).isoformat(),
    "model": "YIJIAN-Qwen3-14B-LoRA-gold-runtime-v3-BF16",
    "adapterPath": "/persistent/yijian/models/yijian-lora-v3-frozen/adapter",
    "passed": bool(passed),
    "recommendedGpuMemoryUtilization": min(map(float, passed)) if passed else None,
    "passingProfiles": passed,
    "failedProfiles": failed,
    "profileReports": reports,
}
output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(value, ensure_ascii=False))
PY

[[ ${#passed[@]} -gt 0 ]] || exit 4
