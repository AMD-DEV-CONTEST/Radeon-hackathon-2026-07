#!/usr/bin/env bash
# grade.sh — the harness owns compilation, execution and judgement.
# The agent's opinion of its own kernel is not consulted.
set -uo pipefail
HIPCC="${HIPCC:-$HOME/.local/bin/hipcc}"
TOL="${TOL:-1e-2}"
[ -f agent_kernel.cuh ] || { echo "VERDICT: NO SUBMISSION (agent_kernel.cuh absent)"; exit 2; }
[ -f golden_out.bin ]   || { echo "VERDICT: NO GOLDEN (run ./golden_gen)"; exit 2; }
if ! "$HIPCC" --offload-arch=gfx1201 -O3 repro_harness.cu -o repro 2>/tmp/agent_build.log; then
  echo "VERDICT: DID NOT COMPILE"; sed -n '1,12p' /tmp/agent_build.log; exit 1
fi
OUT=$(HIP_VISIBLE_DEVICES=0 timeout 300 ./repro 2>&1) || { echo "VERDICT: CRASHED"; echo "$OUT"; exit 1; }
echo "$OUT"
ERR=$(echo "$OUT" | grep -oE 'max_rel_err=[0-9.e+-]+' | cut -d= -f2)
[ -n "$ERR" ] || { echo "VERDICT: NO ERROR REPORTED"; exit 1; }
if python3 -c "import sys; sys.exit(0 if float('$ERR') <= float('$TOL') else 1)"; then
  echo "VERDICT: REPRODUCED  (max_rel_err=$ERR <= tol=$TOL)"
else
  echo "VERDICT: FAILED      (max_rel_err=$ERR  > tol=$TOL)"; exit 1
fi
