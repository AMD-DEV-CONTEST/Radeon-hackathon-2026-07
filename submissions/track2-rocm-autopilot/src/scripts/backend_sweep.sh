#!/usr/bin/env bash
# Scripted attention-backend sweep at the agent's winning config
# (max_num_seqs 128, prefix caching on, concurrency 32). TRITON_ATTN is
# already covered by agent-iter-2; each other backend gets restart + bench.
# A backend that fails to load is journaled as a finding, not skipped silently.
set -u
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1

for BACKEND in ROCM_ATTN FLASH_ATTN ROCM_AITER_UNIFIED_ATTN; do
  echo "SWEEP $BACKEND restart $(date +%T)"
  if bash scripts/restart_vllm.sh "$BACKEND" 128 true; then
    python - "$BACKEND" <<'EOF'
import sys
from autopilot.bench_runner import run_benchmark
from autopilot.journal import Journal
backend = sys.argv[1]
j = Journal()
r = run_benchmark({"max_num_seqs": 128, "enable_prefix_caching": True, "concurrency": 32})
if "error" in r:
    j.add_note(f"backend sweep {backend}: bench failed: {r['error'][:300]}")
    print("SWEEP", backend, "BENCH_ERROR")
else:
    r["config"]["attention_backend"] = backend
    j.add_run(r, f"Scripted backend sweep: {backend} at the agent's winning config "
                 "(mns 128, prefix on, conc 32).", label=f"backend-{backend}")
    print("SWEEP", backend, r["metrics"], r["energy"])
EOF
  else
    python - "$BACKEND" <<'EOF'
import sys
from autopilot.journal import Journal
backend = sys.argv[1]
Journal().add_note(f"backend sweep: {backend} failed to load on gfx1100 "
                   "(vLLM 0.16.1 rocm build); previous config restored. Documented finding.")
print("SWEEP", backend, "LOAD_FAILED (documented)")
EOF
  fi
done
echo "SWEEP restoring TRITON_ATTN winner config"
bash scripts/restart_vllm.sh TRITON_ATTN 128 true
mkdir -p /persistent/rocm-autopilot-results
cp -f runs/journal.jsonl runs/state.json /persistent/rocm-autopilot-results/ 2>/dev/null
echo "SWEEP all:done"
