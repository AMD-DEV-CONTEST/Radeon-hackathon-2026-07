#!/usr/bin/env bash
# ROCKY complete unused-instruction sweep: for a built llama.cpp/ggml tree, recompile
# every COMPUTE kernel with --save-temps and cross-reference the emitted gfx ISA against
# the PRESENT-in-HW census (scan-isa-gfx.sh) => the definitive "in silicon, 0 uses" list.
# Reliable (per-kernel recompile via compile_commands.json); does NOT trust roc-obj/.so
# unbundle (both proved flaky on this tree). CPU-only, no GPU.
#
# Usage: unused-isa-sweep.sh <build_dir> [gfx1201]   > report.md
set -uo pipefail
BUILD="${1:?usage: unused-isa-sweep.sh <build_dir> [arch]}"
ARCH="${2:-gfx1201}"
CC="$BUILD/compile_commands.json"
SDK="${ROCM_PATH:-/home/jmonk/miniconda3/envs/qat714/lib/python3.12/site-packages/_rocm_sdk_devel}"
OBJD="$SDK/lib/llvm/bin/llvm-objdump"
OUT="$(mktemp -d)"; SDIR="$OUT/s"; mkdir -p "$SDIR"

# 1) candidate compute kernels: matmul / attention / quant / convert families + any file
#    that references a matrix/dot intrinsic in source (where wmma/swmmac/dot8 can appear).
mapfile -t CAND < <(python3 - "$CC" <<'PY'
import json,sys,re
cc=json.load(open(sys.argv[1]))
pat=re.compile(r'(mmq|mmv[fq]|mmvq|mmf|mul_mat|fattn|convert|cpy|iu4|int4|dequant|quantize)', re.I)
seen=set()
for e in cc:
    f=e['file']
    if f.endswith('.cu') and pat.search(f) and f not in seen:
        seen.add(f); print(f)
PY
)
echo "# unused-instruction sweep — arch=$ARCH  build=$BUILD"
echo "candidate compute kernels: ${#CAND[@]}"

# 2) recompile each with --save-temps=obj (parallel), collect the device .s
compile_one(){
  local f="$1"
  local line; line="$(python3 - "$CC" "$f" <<'PY'
import json,sys
for e in json.load(open(sys.argv[1])):
    if e['file']==sys.argv[2]: print(e['command']); print(e['directory']); break
PY
)"
  local cmd dir; cmd="$(printf '%s\n' "$line" | sed -n 1p)"; dir="$(printf '%s\n' "$line" | sed -n 2p)"
  [ -z "$cmd" ] && return
  ( cd "$dir" && timeout 400 bash -c "$cmd --save-temps=obj" >/dev/null 2>&1 )
  local s; s="$(find "$BUILD" -name "*$(basename "$f" .cu)*$ARCH*.s" 2>/dev/null | head -1)"
  [ -n "$s" ] && cp "$s" "$SDIR/$(basename "$f" .cu).s" 2>/dev/null
}
export -f compile_one; export CC BUILD ARCH SDIR
printf '%s\n' "${CAND[@]}" | xargs -P 16 -I{} bash -c 'compile_one "{}"'
echo "kernels with emitted ISA: $(ls "$SDIR" 2>/dev/null | wc -l)"

# 3) cross-ref: every PRESENT-in-HW instruction -> total emitted + which kernels
declare -a CENSUS=(
  v_wmma_f32_16x16x16_f16 v_wmma_f32_16x16x16_bf16 v_wmma_f32_16x16x16_fp8 v_wmma_f32_16x16x16_bf8
  v_wmma_i32_16x16x16_iu8 v_wmma_i32_16x16x32_iu4
  v_swmmac_f32_16x16x32_fp8 v_swmmac_f32_16x16x32_f16 v_swmmac_i32_16x16x64_iu4
  v_dot8_i32_iu4 v_dot4_i32_iu8 v_dot4_f32_fp8 v_dot2_f32_f16 v_dot2_f32_bf16
  v_cvt_pk_fp8 v_cvt_pk_bf8 v_cvt_sr_fp8 v_pk_fma_f16 v_pk_mul_f16
)
echo ""; printf "%-30s %8s   %s\n" "INSTRUCTION (PRESENT in HW)" "EMITTED" "KERNELS (or UNUSED)"
for op in "${CENSUS[@]}"; do
  total=0; hits=""
  for s in "$SDIR"/*.s; do
    [ -e "$s" ] || continue
    c=$("$OBJD" -d --mcpu="$ARCH" "$s" 2>/dev/null | grep -ciE "$op")
    if [ "$c" -gt 0 ]; then total=$((total+c)); hits="$hits $(basename "$s" .s):$c"; fi
  done
  if [ "$total" -eq 0 ]; then printf "%-30s %8s   *** UNUSED (in silicon, 0 uses) ***\n" "$op" "0"
  else printf "%-30s %8s  %s\n" "$op" "$total" "$hits"; fi
done
rm -rf "$OUT"
