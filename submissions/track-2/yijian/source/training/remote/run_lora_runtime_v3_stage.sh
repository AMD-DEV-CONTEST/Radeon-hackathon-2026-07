#!/usr/bin/env bash
set -euo pipefail

STAGE="${1:?stage must be smoke, micro, or full}"
ROOT="${YIJIAN_LORA_V3_ROOT:-/workspace/yijian/lora-runtime-v3-lr3e5}"
MODEL="${YIJIAN_QWEN3_14B_MODEL:-/workspace/yijian/qwen3-14b-bf16}"
REVISION="${YIJIAN_QWEN3_14B_REVISION:-40c069824f4251a91eefaf281ebe4c544efd3e18}"
PYTHON_BIN="${YIJIAN_TRAIN_PYTHON:-/workspace/yijian-venv/bin/python}"
LEARNING_RATE="${YIJIAN_LORA_V3_LEARNING_RATE:-3e-5}"
RUN="$ROOT/runs/$STAGE"

case "$STAGE" in smoke|micro|full) ;; *) echo "unknown stage: $STAGE" >&2; exit 2 ;; esac
test -x "$PYTHON_BIN"
test -f "$MODEL/config.json"
test -f "$ROOT/audits/tokenizer-audit.json"
test ! -e "$RUN" || { echo "refusing to overwrite run: $RUN" >&2; exit 3; }
mkdir -p "$ROOT/runs" "$ROOT/logs"

restore_preview() {
  "$ROOT/bin/start_previous_preview.sh" >>"$ROOT/logs/restore-preview-$STAGE.log" 2>&1 || true
}
trap restore_preview EXIT

# The W7900 must be exclusive during BF16 training.  Stop either competition
# fallback and both old/new 14B preview processes, then verify VRAM is released.
mapfile -t service_pids < <(pgrep -f 'llama-server.*--port (8082|8083)' || true)
if ((${#service_pids[@]})); then
  kill "${service_pids[@]}" || true
fi
pkill -f '[s]erve_lora_transformers.py' || true
for _ in $(seq 1 60); do
  pgrep -f 'llama-server.*--port (8082|8083)' >/dev/null || break
  sleep 1
done
if pgrep -f 'llama-server.*--port (8082|8083)' >/dev/null; then
  echo "inference service did not stop; refusing v3 training" >&2
  exit 4
fi

export PYTORCH_HIP_ALLOC_CONF="${PYTORCH_HIP_ALLOC_CONF:-expandable_segments:True}"
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
common=(
  --model "$MODEL"
  --model-revision "$REVISION"
  --eval "$ROOT/data/agent_sft_dev.jsonl"
  --output "$RUN"
  --max-length 1536
  --max-peak-reserved-gib 45
  --learning-rate "$LEARNING_RATE"
  --lora-rank 8
  --lora-alpha 16
  --lora-dropout 0.10
  --lora-target-modules q_proj,k_proj,v_proj,o_proj
)

case "$STAGE" in
  smoke)
    "$PYTHON_BIN" "$ROOT/bin/train_lora_rocm.py" "${common[@]}" \
      --manifest "$ROOT/micro/micro-manifest.json" \
      --train "$ROOT/micro/micro_train_8.jsonl" \
      --epochs 1 --max-steps 4 --gradient-accumulation 1 \
      --expected-optimizer-steps 4
    ;;
  micro)
    "$PYTHON_BIN" "$ROOT/bin/train_lora_rocm.py" "${common[@]}" \
      --manifest "$ROOT/micro/micro-manifest.json" \
      --train "$ROOT/micro/micro_train_8.jsonl" \
      --epochs 1 --max-steps 30 --gradient-accumulation 1 \
      --require-loss-drop --minimum-relative-loss-drop 0.05 \
      --expected-optimizer-steps 30
    ;;
  full)
    "$PYTHON_BIN" "$ROOT/bin/train_lora_rocm.py" "${common[@]}" \
      --manifest "$ROOT/data/manifest.json" \
      --train "$ROOT/data/agent_sft_train.jsonl" \
      --epochs 2 --gradient-accumulation 16 \
      --require-dev-loss-drop --require-dev-task-gates \
      --expected-optimizer-steps 90 --expected-epochs 2
    ;;
esac
