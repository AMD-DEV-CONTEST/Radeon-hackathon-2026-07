#!/bin/bash
# Wait for v3_regular to finish, then auto-launch v3_cloaked.
# This is the sequential handoff so both A/B runs complete without manual kick.

set -u
cd /c/Dev/Determinex

REG_NAME="mass_run_v3_regular"
CLK_NAME="mass_run_v3_cloaked"
TASKS_FILE="/tmp/pb_full_tasks.txt"

echo "[handoff] $(date -Iseconds) — waiting for $REG_NAME to finish..."

# Poll every 60s for the regular agent process to die.
# Process detection: any python running determinex_programbench_agent with the regular run-name.
while pgrep -af "determinex_programbench_agent.*$REG_NAME" >/dev/null 2>&1; do
    sleep 60
done

echo "[handoff] $(date -Iseconds) — $REG_NAME finished. Launching $CLK_NAME with DETERMINEX_CLOAK=1..."

# Brief pause for Ollama to release any held resources.
sleep 30

DETERMINEX_CLOAK=1 DETERMINEX_CLOAK_AUDIT=1 PYTHONUNBUFFERED=1 \
    python scripts/determinex_programbench_agent.py \
    --workers 1 \
    --run-name "$CLK_NAME" \
    --model local \
    --local-model qwen2.5-coder:7b-instruct \
    --escalate \
    --tasks $(cat "$TASKS_FILE") \
    2>&1 | tee "logs/${CLK_NAME}_$(date +%s).log"

echo "[handoff] $(date -Iseconds) — $CLK_NAME finished."
