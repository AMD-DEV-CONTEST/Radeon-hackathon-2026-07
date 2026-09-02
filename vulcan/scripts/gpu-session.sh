#!/usr/bin/env bash
# One GPU session, start to finish. Credits bill at 1 per GPU-hour and the
# account holds 5, so the session is scripted rather than improvised: every
# minute spent typing on the instance is a minute of budget.
#
#   ssh <instance> 'bash -s' < scripts/gpu-session.sh
#
# Leaves bench-results/*.json on the instance; scp them back before destroying.
set -euo pipefail

BASE_URL="${VULCAN_BASE_URL:-http://localhost:8000/v1}"
MODEL="${VULCAN_MODEL:-Qwen/Qwen3-8B}"
LABEL="${LABEL:-radeon-vllm-fp16}"
DEMO_REPO="${DEMO_REPO:-$HOME/demo-repo}"
REPEATS="${REPEATS:-5}"

export VULCAN_BASE_URL="$BASE_URL"
export VULCAN_MODEL="$MODEL"
export VULCAN_EMBED_MODEL="${VULCAN_EMBED_MODEL:-$MODEL}"

say() { printf '\n=== %s ===\n' "$1"; }

say "Waiting for vLLM at $BASE_URL"
for i in $(seq 1 90); do
  if curl -sf "$BASE_URL/models" >/dev/null 2>&1; then
    echo "up after ${i}0s"
    break
  fi
  if [ "$i" -eq 90 ]; then
    echo "vLLM never came up. Check the serve command and the container logs." >&2
    exit 1
  fi
  sleep 10
done

curl -sf "$BASE_URL/models" | head -c 400; echo

say "Installing vulcan"
cd "$(dirname "$0")/.."
pip install -q -e .

say "Fetching a demo repo"
# A real, moderately sized repo: indexing vulcan's own source looks trivial on camera.
if [ ! -d "$DEMO_REPO" ]; then
  git clone --depth 1 https://github.com/pallets/flask "$DEMO_REPO"
fi

say "Indexing $DEMO_REPO"
time vulcan index "$DEMO_REPO"

say "Smoke test"
cd "$DEMO_REPO"
vulcan ask "where is the request context pushed and popped?"
cd - >/dev/null

say "Benchmarking $LABEL"
vulcan bench --label "$LABEL" --repeats "$REPEATS"

say "Comparison against the laptop baseline"
vulcan bench-compare bench-results/ollama-m4air-qwen3-4b.json "bench-results/$LABEL.json"

say "Done. scp bench-results/ back, then DESTROY the instance"
echo "Credits keep burning until the instance is destroyed:"
echo "  DELETE https://radeon-global.anruicloud.com/api/notebook/current"
