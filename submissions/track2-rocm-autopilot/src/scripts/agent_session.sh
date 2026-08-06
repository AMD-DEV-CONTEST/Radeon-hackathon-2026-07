#!/usr/bin/env bash
# Overnight agent session runner (Radeon instance).
# Loads .env, runs the autonomous optimization loop, tees everything to a
# session log, and mirrors results to the persistent volume after each phase.
set -u
cd "$(dirname "$0")/.."

set -a; source .env; set +a
export PATH=/opt/venv/bin:$PATH
export PYTHONUNBUFFERED=1

STAMP=$(date +%Y%m%d-%H%M)
LOG="runs/session-$STAMP.log"
mkdir -p runs /persistent/rocm-autopilot-results 2>/dev/null || true

sync_results() {
  cp -f runs/journal.jsonl runs/state.json "$LOG" /persistent/rocm-autopilot-results/ 2>/dev/null || true
  cp -f /workspace/vllm_serve.log /persistent/rocm-autopilot-results/ 2>/dev/null || true
}

echo "=== agent session $STAMP · $(python -m autopilot.power 2>/dev/null | tail -1) ===" | tee -a "$LOG"

ITERS="${1:-8}"
python -m autopilot.agent --iters "$ITERS" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
echo "=== agent exited rc=$rc ===" | tee -a "$LOG"
sync_results
exit "$rc"
