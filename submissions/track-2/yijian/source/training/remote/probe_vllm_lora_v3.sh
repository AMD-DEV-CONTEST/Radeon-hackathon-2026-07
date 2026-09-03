#!/usr/bin/env bash
# Reversible W7900 probe for the frozen YIJIAN LoRA v3 on AMD's ROCm vLLM.
set -euo pipefail

VLLM=/workspace/yijian/vllm-venv/bin/vllm
BASE=/workspace/yijian/qwen3-14b-bf16
ADAPTER=/persistent/yijian/models/yijian-lora-v3-frozen/adapter
ALIAS=YIJIAN-Qwen3-14B-LoRA-gold-runtime-v3-Q4
PORT=8083
LOG=/workspace/yijian/vllm-lora-v3-probe.log
PID_FILE=/workspace/yijian/vllm-lora-v3-probe.pid
RESTORE_14B=/workspace/yijian/lora-runtime-v3-lr3e5/bin/start_lora14b_v3_fast_preview.sh
RESTORE_27B=/workspace/yijian/lora-gold-v2/bin/restore_27b.sh

test -x "$VLLM"
test -f "$BASE/config.json"
test -f "$ADAPTER/adapter_config.json"

stop_llama_port() {
  local port="$1"
  mapfile -t pids < <(pgrep -f "llama-server.*--port $port" || true)
  if ((${#pids[@]})); then
    kill "${pids[@]}"
  fi
  for _ in $(seq 1 60); do
    pgrep -f "llama-server.*--port $port" >/dev/null || return 0
    sleep 1
  done
  echo "llama-server on port $port did not stop" >&2
  return 1
}

restore_previous() {
  "$RESTORE_14B" >/workspace/yijian/restore-lora-v3-after-vllm-probe.log 2>&1 || true
  "$RESTORE_27B" >/workspace/yijian/restore-27b-after-vllm-probe.log 2>&1 || true
}

probe_failed=1
on_exit() {
  if [[ "$probe_failed" == 1 ]]; then
    if [[ -f "$PID_FILE" ]]; then
      pid="$(tr -dc '0-9' < "$PID_FILE")"
      [[ -z "$pid" || ! -d "/proc/$pid" ]] || kill "$pid" || true
    fi
    restore_previous
  fi
}
trap on_exit EXIT

stop_llama_port 8082
stop_llama_port 8083

export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
# The environment contains an optional Quark plugin built against another
# vLLM snapshot.  An empty allow-list disables third-party default plugins.
export VLLM_PLUGINS=""

nohup "$VLLM" serve "$BASE" \
  --served-model-name Qwen3-14B \
  --host 127.0.0.1 --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len 8192 --max-num-seqs 2 \
  --gpu-memory-utilization 0.72 \
  --enable-prefix-caching \
  --enable-lora --max-lora-rank 16 \
  --lora-modules "$ALIAS=$ADAPTER" \
  >"$LOG" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 300); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -Fq "$ALIAS"; then
    probe_failed=0
    curl -fsS "http://127.0.0.1:$PORT/v1/models"
    exit 0
  fi
  pid="$(tr -dc '0-9' < "$PID_FILE")"
  [[ -n "$pid" && -d "/proc/$pid" ]] || break
  sleep 1
done

tail -160 "$LOG" >&2 || true
echo "ROCm vLLM LoRA v3 probe failed; previous services will be restored" >&2
exit 1
