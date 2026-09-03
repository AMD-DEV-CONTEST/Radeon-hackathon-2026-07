#!/usr/bin/env bash
# Does the route's win/lose crossover move with SHAPE, or is M sufficient?
# Same M values, two models of different width. If the crossover is at a
# different M for each, a scalar MTHRESH cannot be correct for both.
set -uo pipefail
# Point these at your own build and models.
B=${LLAMA_BENCH:-./build/bin/llama-bench}
[ -n "${ROCM_ENV:-}" ] && source "$ROCM_ENV" 2>/dev/null
export HIP_VISIBLE_DEVICES=0
declare -A MODELS=(
 [8B]=${MODEL_8B:-sparse-llama-8b-2of4-Q4_K.gguf}
 [24B]=${MODEL_24B:-Devstral-Small-2507-Q4_K_M.gguf}
)
for tag in 8B 24B; do
  M=${MODELS[$tag]}
  [ -f "$M" ] || { echo "  $tag: model missing ($M)"; continue; }
  echo "=== $tag  $(basename $M) ==="
  printf "  %-6s %12s %12s %8s\n" "ubatch" "route OFF" "route ON" "delta"
  for ub in 64 128 256 512; do
    off=$(timeout -s KILL 900 $B -m "$M" -p 512 -n 0 -ub $ub -r 2 2>/dev/null | grep -aE 'pp512' | tail -1 | awk -F'|' '{gsub(/ /,"",$(NF-1)); print $(NF-1)}')
    on=$(GGML_HIP_Q4_K_HIPBLASLT_PREFILL=1 GGML_HIP_Q4_K_HIPBLASLT_MTHRESH=0 \
         GGML_HIP_Q4_K_HIPBLASLT_TUNE_CACHE=/tmp/xover-$tag-$ub.bin \
         timeout -s KILL 900 $B -m "$M" -p 512 -n 0 -ub $ub -r 2 2>/dev/null | grep -aE 'pp512' | tail -1 | awk -F'|' '{gsub(/ /,"",$(NF-1)); print $(NF-1)}')
    d=$(python3 -c "
try:
    o,n=float('${off:-0}'),float('${on:-0}')
    print(f'{(n-o)/o*100:+.1f}%' if o>0 else 'n/a')
except: print('n/a')")
    printf "  %-6s %12s %12s %8s\n" "$ub" "${off:-fail}" "${on:-fail}" "$d"
  done
  echo
done
