#!/usr/bin/env bash
set -uo pipefail
FMT="${1:?usage: grade.sh Q1|Q2}"; TOL="${TOL:-1e-2}"
HIPCC="${HIPCC:-$HOME/.local/bin/hipcc}"
[ -f agent_kernel.cuh ] || { echo "VERDICT: NO SUBMISSION"; exit 2; }
if ! "$HIPCC" --offload-arch=gfx1201 -O3 -DFMT_$FMT repro_harness.cu -o repro_$FMT 2>/tmp/q_build.log; then
  echo "VERDICT: DID NOT COMPILE"; sed -n '1,10p' /tmp/q_build.log; exit 1; fi
OUT=$(HIP_VISIBLE_DEVICES=0 timeout 300 ./repro_$FMT 2>&1) || { echo "VERDICT: CRASHED"; echo "$OUT"; exit 1; }
echo "$OUT"
ERR=$(echo "$OUT" | grep -oE 'max_rel_err=[0-9.e+-]+' | cut -d= -f2)
[ -n "$ERR" ] || { echo "VERDICT: NO ERROR REPORTED"; exit 1; }
if python3 -c "import sys;sys.exit(0 if float('$ERR')<=float('$TOL') else 1)"; then
  echo "VERDICT: REPRODUCED  (max_rel_err=$ERR <= $TOL)"
else echo "VERDICT: FAILED      (max_rel_err=$ERR > $TOL)"; exit 1; fi
