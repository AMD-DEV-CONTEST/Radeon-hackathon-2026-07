#!/usr/bin/env bash
# Fully detached overnight pipeline (Radeon instance). Survives SSH loss.
# 1. (Re)launch the deployment  2. smoke-test tool calling
# 3. journaled baseline benchmark  4. agent session  5. mirror results.
# Progress markers go to /workspace/pipeline.log; grep PHASE to follow.
set -u
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1

phase() { echo "PHASE $1 $(date +%F-%T)"; }

phase "launch:start"
# Native-architecture serving (gemma3 is in this build's registry). The
# transformers fallback path is broken for gemma4 here: config rejected on
# stock transformers 4.57, silent native crash mid-load on 5.14 (documented).
export SERVE_EXTRA_FLAGS="${SERVE_EXTRA_FLAGS:---enable-auto-tool-choice --tool-call-parser functiongemma --max-model-len 8192}"
export HEALTH_TRIES=140
if ! bash scripts/restart_vllm.sh TRITON_ATTN 256 true; then
  phase "launch:FAILED"; tail -30 /workspace/vllm_serve.log; exit 1
fi
phase "launch:ok"

phase "smoke:start"
SMOKE=$(curl -sf -m 120 http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$BENCH_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK.\"}],\"max_tokens\":8}")
echo "smoke chat: $SMOKE"
TOOLSMOKE=$(curl -sf -m 120 http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$BENCH_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in Paris? Use the tool.\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"description\":\"Get weather for a city\",\"parameters\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}}}],\"tool_choice\":\"auto\",\"max_tokens\":128}")
echo "smoke tool: $TOOLSMOKE"
echo "$TOOLSMOKE" | grep -q "tool_calls" && phase "smoke:tool_calls_OK" || phase "smoke:tool_calls_MISSING (agent JSON fallback will engage)"

phase "baseline:start"
python - <<'EOF'
from autopilot.bench_runner import run_benchmark
from autopilot.journal import Journal
j = Journal()
r = run_benchmark({"max_num_seqs": 256, "enable_prefix_caching": True, "concurrency": 8})
if "error" in r:
    print("baseline error:", r["error"])
else:
    j.add_run(r, "Scripted baseline: vLLM-ROCm defaults before the agent touches anything "
                 "(TRITON_ATTN, max_num_seqs 256, prefix caching on, concurrency 8).",
              label="baseline-default")
    print("baseline:", r["metrics"], r["energy"])
EOF
phase "baseline:done"

phase "agent:start"
bash scripts/agent_session.sh "${AGENT_ITERS:-6}"
phase "agent:done"

mkdir -p /persistent/rocm-autopilot-results
cp -f runs/journal.jsonl runs/state.json runs/session-*.log /persistent/rocm-autopilot-results/ 2>/dev/null || true
cp -f /workspace/vllm_serve.log /workspace/pipeline.log /persistent/rocm-autopilot-results/ 2>/dev/null || true
phase "all:done"
