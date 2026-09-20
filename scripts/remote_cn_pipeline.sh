#!/usr/bin/env bash
set -euo pipefail

PROJECT=/persistent/radeon-repo/track2-agentic-ai
TRAIN_PID_FILE=/persistent/cn_qlora_train.pid
PIPELINE_LOG=/persistent/cn_auto_pipeline.log
ADAPTER=/persistent/qwen-trader-cn-lora/final
MERGED=/persistent/qwen-trader-cn-merged

exec >>"$PIPELINE_LOG" 2>&1
echo "[$(date -Is)] pipeline started"

if [[ -f "$TRAIN_PID_FILE" ]]; then
  train_pid=$(cat "$TRAIN_PID_FILE")
  while kill -0 "$train_pid" 2>/dev/null; do
    echo "[$(date -Is)] training PID $train_pid still running"
    sleep 60
  done
fi

if [[ ! -f "$ADAPTER/adapter_model.safetensors" ]]; then
  echo "[$(date -Is)] ERROR: adapter missing: $ADAPTER"
  exit 1
fi

echo "[$(date -Is)] merging domestic adapter"
cd "$PROJECT"
/opt/venv/bin/python training/scripts/merge_lora.py \
  --base-model /persistent/qwen-trader-merged \
  --adapter-path "$ADAPTER" \
  --output-path "$MERGED"

echo "[$(date -Is)] starting domestic vLLM"
nohup env VLLM_USE_TRITON_FLASH_ATTN=0 /opt/venv/bin/python -m vllm.entrypoints.openai.api_server \
  --model "$MERGED" --served-model-name models/qwen-trader-merged \
  --port 8000 --max-model-len 4096 --gpu-memory-utilization 0.50 \
  --dtype float16 --trust-remote-code --enforce-eager \
  >/persistent/cn_vllm.log 2>&1 &
echo $! >/persistent/cn_vllm.pid

for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/v1/models >/dev/null; then
    break
  fi
  sleep 10
done
curl -fsS http://127.0.0.1:8000/v1/models >/dev/null

echo "[$(date -Is)] evaluating domestic model"
/opt/venv/bin/python scripts/eval_cn_market.py \
  --vllm-url http://127.0.0.1:8000/v1 \
  --model models/qwen-trader-merged \
  --output /persistent/cn_market_eval_after.json \
  >/persistent/cn_market_eval_after.log 2>&1

sha256sum "$ADAPTER/adapter_model.safetensors" "$MERGED"/*.safetensors \
  >/persistent/cn_model_sha256.txt
echo "[$(date -Is)] pipeline complete"
