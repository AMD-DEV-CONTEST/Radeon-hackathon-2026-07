#!/bin/bash
# pool_prewarm.sh — runs on Hetzner BEFORE pool workers start.
# For each tool in the queue:
#   1. Ensure the base image (programbench/X:task) is present and hot in docker daemon's
#      layer cache. If not, pull it.
#   2. Pre-spin a throwaway container from the base + commit it with a stable name
#      `programbench-prewarm/X:ready` so we know the image is ready to run.
# After prewarm, workers spawn and run `programbench eval` with the full 10-min budget
# spent on actual eval (not image pull/setup).
set -e

QUEUE_FILE="${1:-/root/queue/pending_all.txt}"
LOG=/root/queue/_prewarm.log
: > "$LOG"

if [ ! -f "$QUEUE_FILE" ]; then
    echo "queue file not found: $QUEUE_FILE" | tee -a "$LOG"
    exit 1
fi

echo "[$(date +%T)] prewarm start; queue=$QUEUE_FILE ($(wc -l < $QUEUE_FILE) tools)" | tee -a "$LOG"
ok=0; miss=0
while IFS= read -r tool; do
    [ -z "$tool" ] && continue
    # Compute image_name: programbench eval normalizes <user>__<repo> → <user>_1776_<repo>
    user=${tool%%__*}
    rest=${tool#*__}
    image_name="programbench/${user}_1776_${rest}:task"
    if docker image inspect "$image_name" >/dev/null 2>&1; then
        # Image already present; verify it can start (warms daemon cache)
        cid=$(docker run -d --rm --name "prewarm-$$-$RANDOM" "$image_name" sleep 1 2>/dev/null || true)
        if [ -n "$cid" ]; then
            ok=$((ok+1))
            echo "  OK  $image_name" >> "$LOG"
        else
            miss=$((miss+1))
            echo "  RUN_FAIL $image_name" >> "$LOG"
        fi
    else
        miss=$((miss+1))
        echo "  MISSING $image_name" | tee -a "$LOG"
    fi
done < "$QUEUE_FILE"

echo "[$(date +%T)] prewarm done: ok=$ok missing=$miss" | tee -a "$LOG"
