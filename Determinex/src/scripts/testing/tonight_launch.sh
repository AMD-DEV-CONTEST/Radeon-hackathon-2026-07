#!/bin/bash
# tonight_launch.sh — Watch corpus, then fire pod training the moment it lands
# Run this NOW: bash scripts/tonight_launch.sh
# It will block until corpus is done, then do everything automatically.

set -euo pipefail

POD_HOST="${RUNPOD_HOST:?set RUNPOD_HOST=<pod-ip>}"
POD_PORT="${RUNPOD_PORT:-22}"
POD_KEY="$HOME/.ssh/id_runpod"
SSH="ssh -p $POD_PORT -i $POD_KEY -o StrictHostKeyChecking=no $POD_HOST"
SCP="scp -P $POD_PORT -i $POD_KEY -o StrictHostKeyChecking=no"
DETERMINEX="$(cd "$(dirname "$0")/.." && pwd)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── 1. Wait for corpus ────────────────────────────────────────────────────────
log "Watching corpus expansion..."
while true; do
    if [ -f "$DETERMINEX/data/rosetta_training.jsonl" ]; then
        LINES=$(wc -l < "$DETERMINEX/data/rosetta_training.jsonl")
        if [ "$LINES" -ge 18000 ]; then
            log "Corpus ready: $LINES examples"
            break
        fi
    fi
    log "  expanding..."
    sleep 60
done

# ── 2. Split corpus ───────────────────────────────────────────────────────────
log "Splitting corpus..."
python3 "$DETERMINEX/dataset_generation/generate_rosetta_corpus.py" --split --data-dir "$DETERMINEX/data"
log "Split done:"
wc -l "$DETERMINEX/data/rosetta_train.jsonl" "$DETERMINEX/data/lora_train.jsonl"

# ── 3. Upload to pod ──────────────────────────────────────────────────────────
log "Setting up pod workspace..."
$SSH "mkdir -p /workspace/data /workspace/outputs"

log "Uploading corpus (this takes a minute)..."
$SCP "$DETERMINEX/data/rosetta_train.jsonl" "$POD_HOST:/workspace/data/"
$SCP "$DETERMINEX/data/lora_train.jsonl"    "$POD_HOST:/workspace/data/"

log "Uploading training data files..."
# Merge all curriculum + DSL files into one data dir
for f in "$DETERMINEX/scripts/curriculum.jsonl" \
          "$DETERMINEX/scripts/dsl_corpus_merged.jsonl" \
          "$DETERMINEX/auto_curriculum.jsonl"; do
    [ -f "$f" ] && $SCP "$f" "$POD_HOST:/workspace/data/" && log "  ↑ $(basename $f)"
done

# All gap curriculum files
for f in "$DETERMINEX/scripts/"gap_v*.jsonl; do
    [ -f "$f" ] && $SCP "$f" "$POD_HOST:/workspace/data/" 2>/dev/null || true
done

log "Uploading training scripts..."
$SCP "$DETERMINEX/scripts/train_rosetta_bases.py" "$POD_HOST:/workspace/"
$SCP "$DETERMINEX/scripts/dsl_finetune.py"         "$POD_HOST:/workspace/"

# ── 4. Kill vLLM ─────────────────────────────────────────────────────────────
log "Stopping vLLM to free VRAM..."
$SSH "pkill -f 'vllm.entrypoints' 2>/dev/null || true; sleep 3; nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader"

# ── 5. Fire Rosetta training ──────────────────────────────────────────────────
log "Launching Rosetta Stone training on pod..."
$SSH "
    cd /workspace
    export HF_TOKEN='${HF_TOKEN:-}'
    nohup python3 train_rosetta_bases.py \
        --data-dir   /workspace/data \
        --out-dir    /workspace/rosetta_out \
        --cache-dir  /workspace/rosetta_cache \
        > /workspace/rosetta_train.log 2>&1 &
    echo \$! > /workspace/rosetta.pid
    echo 'Rosetta PID:'\$(cat /workspace/rosetta.pid)
"

log "Tailing Rosetta log (Ctrl+C when you want to detach — training keeps going)..."
$SSH "tail -f /workspace/rosetta_train.log" || true

# ── 6. Wait for Rosetta, then fire LoRA ──────────────────────────────────────
log "Polling for rosetta_v1.pt..."
while ! $SSH "[ -f /workspace/rosetta_out/rosetta_v1.pt ]" 2>/dev/null; do
    LAST=$($SSH "tail -1 /workspace/rosetta_train.log 2>/dev/null" || echo "...")
    log "  $LAST"
    sleep 45
done
log "rosetta_v1.pt done!"

log "Downloading rosetta_v1.pt..."
mkdir -p "$HOME/.determinex/rosetta"
$SCP "$POD_HOST:/workspace/rosetta_out/rosetta_v1.pt" "$HOME/.determinex/rosetta/"

# ── 7. LoRA fine-tune sequence ────────────────────────────────────────────────
log "Starting LoRA fine-tune sequence: observer → engineer → sentinel"
$SSH "
    export HF_TOKEN='${HF_TOKEN:-}'
    cd /workspace
    nohup bash -c '
        set -e
        echo STAGE:observer-start
        python3 dsl_finetune.py observer > /workspace/retrain_observer.log 2>&1
        echo STAGE:observer-done
        python3 dsl_finetune.py engineer > /workspace/retrain_engineer.log 2>&1
        echo STAGE:engineer-done
        python3 dsl_finetune.py sentinel > /workspace/retrain_sentinel.log 2>&1
        echo STAGE:sentinel-done
        echo ALL_LORA_COMPLETE
    ' > /workspace/lora_master.log 2>&1 &
    echo \$! > /workspace/lora.pid
    echo 'LoRA PID:'\$(cat /workspace/lora.pid)
"

log "========================================================"
log "Pod training is running. Check status anytime:"
log "  ssh root@$POD_HOST -p $POD_PORT -i ~/.ssh/id_runpod 'tail -20 /workspace/lora_master.log'"
log "  ssh root@$POD_HOST -p $POD_PORT -i ~/.ssh/id_runpod 'tail -5 /workspace/retrain_observer.log'"
log ""
log "When LoRA is done, download + register v1.1:"
log "  python scripts/register_v1_1.py"
log ""
log "Then run the final 5-run benchmark:"
log "  python scripts/determinex_benchmark_5run.py --runs 5 --instances 10 --backend ollama"
log "========================================================"
