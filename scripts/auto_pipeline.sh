#!/bin/bash
set -euo pipefail

PYTHON=/opt/venv/bin/python
PERSIST=/workspace/persistent
PROJECT=$PERSIST/radeon-repo/track2-agentic-ai
cd "$PROJECT"

export HF_ENDPOINT=https://hf-mirror.com
export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0
export VLLM_USE_TRITON_FLASH_ATTN=0

mkdir -p "$PERSIST/manifests"

log() { echo "[$(date +%H:%M:%S)] $1"; }

# ===== PHASE 0: Check persistent for existing adapter =====
log "=== PHASE 0: Checking for existing LoRA adapter ==="

ADAPTER_DIR="models/qwen-trader-lora/final"
PERSIST_ADAPTER="$PERSIST/qwen-trader-lora"
PERSIST_MERGED="$PERSIST/qwen-trader-merged"

# Check if adapter already exists in persistent
if [ -f "$PERSIST_ADAPTER/final/adapter_config.json" ]; then
    log "Found existing LoRA adapter in persistent storage — skipping training"
    # Restore from persistent
    mkdir -p models/qwen-trader-lora
    cp -a "$PERSIST_ADAPTER/final" "$ADAPTER_DIR" 2>/dev/null || true
    log "Adapter restored from persistent storage"
else
    log "No existing adapter in persistent storage — waiting for training"
    # Wait for training to complete
    while pgrep -f train_qlora.py > /dev/null 2>&1; do
        STEP=$(grep -oP '\d+/\d+' /tmp/qlora_train.log 2>/dev/null | tail -1 || echo "?")
        log "Training in progress: step $STEP ..."
        sleep 60
    done
    log "Training process finished."

    if [ ! -d "$ADAPTER_DIR" ]; then
        log "ERROR: LoRA adapter not found at $ADAPTER_DIR"
        tail -20 /tmp/qlora_train.log 2>/dev/null
        exit 1
    fi
    log "LoRA adapter found at $ADAPTER_DIR"

    # Immediately copy to persistent
    log "Copying adapter to persistent storage..."
    cp -a models/qwen-trader-lora "$PERSIST_ADAPTER"
    log "Adapter saved to $PERSIST_ADAPTER"
fi

# ===== PHASE 1: Check persistent for existing merged model =====
log "=== PHASE 1: Merging LoRA weights ==="

if [ -f "$PERSIST_MERGED/config.json" ]; then
    log "Found existing merged model in persistent storage — skipping merge"
    mkdir -p models/qwen-trader-merged
    cp -a "$PERSIST_MERGED"/* models/qwen-trader-merged/ 2>/dev/null || true
    log "Merged model restored from persistent storage"
else
    BASE_MODEL=$(ls -d models/hf_cache/models--Qwen--Qwen2.5-7B-Instruct/snapshots/*/ 2>/dev/null | head -1)
    if [ -z "$BASE_MODEL" ]; then
        BASE_MODEL="Qwen/Qwen2.5-7B-Instruct"
    fi
    log "Base model: $BASE_MODEL"

    $PYTHON training/scripts/merge_lora.py \
        --base-model "$BASE_MODEL" \
        --adapter-path "$ADAPTER_DIR" \
        --output-path models/qwen-trader-merged 2>&1

    if [ ! -f "models/qwen-trader-merged/config.json" ]; then
        log "ERROR: Merged model not saved properly"
        exit 1
    fi
    log "Merged model saved to models/qwen-trader-merged"

    # Immediately copy to persistent
    log "Copying merged model to persistent storage..."
    cp -a models/qwen-trader-merged "$PERSIST_MERGED"
    log "Merged model saved to $PERSIST_MERGED"
fi

# ===== PHASE 2: Start vLLM =====
log "=== PHASE 2: Starting vLLM server ==="
fuser -k 8000/tcp 2>/dev/null || true
sleep 2

nohup $PYTHON -m vllm.entrypoints.openai.api_server \
    --model models/qwen-trader-merged \
    --port 8000 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.50 \
    --dtype float16 \
    --trust-remote-code \
    --enforce-eager > /tmp/vllm.log 2>&1 &
VLLM_PID=$!
log "vLLM PID: $VLLM_PID"

# Wait for vLLM to be ready (up to 5 minutes)
log "Waiting for vLLM to start..."
for i in $(seq 1 60); do
    if curl -s http://localhost:8000/v1/models | grep -q "data"; then
        log "vLLM is ready!"
        break
    fi
    if [ "$i" -eq 60 ]; then
        log "ERROR: vLLM failed to start within 5 minutes"
        tail -30 /tmp/vllm.log
        exit 1
    fi
    sleep 5
done

# ===== PHASE 3: Run NL->DSL evaluation =====
log "=== PHASE 3: Running NL->DSL quality evaluation ==="
fuser -k 8080/tcp 2>/dev/null || true
sleep 1
nohup $PYTHON -m uvicorn src.api:app --host 0.0.0.0 --port 8080 > /tmp/api.log 2>&1 &
API_PID=$!
sleep 3

$PYTHON scripts/eval_nl_to_dsl.py --vllm-url http://localhost:8000/v1 --model models/qwen-trader-merged 2>&1 | tee /tmp/eval_results.txt
log "Evaluation complete."

# Copy eval results to persistent
cp /tmp/eval_results.txt "$PERSIST/eval_results.txt" 2>/dev/null || true
cp /tmp/auto_pipeline.log "$PERSIST/auto_pipeline.log" 2>/dev/null || true

# ===== PHASE 4: Summary =====
log "=== PIPELINE COMPLETE ==="
log "Adapter:    $PERSIST_ADAPTER"
log "Merged:     $PERSIST_MERGED"
log "Eval:       $PERSIST/eval_results.txt"
log "vLLM:       http://localhost:8000/v1 (PID $VLLM_PID)"
log "API:        http://localhost:8080 (PID $API_PID)"
