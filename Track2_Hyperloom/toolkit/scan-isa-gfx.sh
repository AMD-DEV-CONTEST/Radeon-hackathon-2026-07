#!/usr/bin/env bash
# ROCKY STEP 0 — scan the SILICON before anything else.
# Ground-truth ISA capability census via llvm-mc (the assembler will not lie):
#   PRESENT  = mnemonic accepted for the arch (assembles / operand-syntax error)
#   ABSENT   = "instruction not supported on this GPU" / "invalid instruction"
# This BYPASSES the clang builtin arity-before-target-feature FALSE POSITIVE
# (a bare `(void)__builtin_...` compiles even for GATED builtins — do NOT trust it).
#
# Usage: scan-isa-gfx.sh [gfx1201]   -> prints a capability map; redirect to save.
set -euo pipefail
ARCH="${1:-gfx1201}"
SDK="${ROCM_PATH:-/opt/rocm}"
MC="$SDK/lib/llvm/bin/llvm-mc"; [ -x "$MC" ] || MC="$(command -v llvm-mc)"

probe(){ # $1 = asm line -> PRESENT / ABSENT
  local out; out=$(printf '%s\n' "$1" | "$MC" -triple=amdgcn -mcpu="$ARCH" -filetype=null 2>&1 || true)
  if   printf '%s' "$out" | grep -qiE 'not supported on|not a recognized|invalid instruction|unknown token in expression'; then echo ABSENT
  elif printf '%s' "$out" | grep -qiE 'invalid operand|expected|too few|too many|unexpected|register'; then echo PRESENT
  elif [ -z "$out" ]; then echo PRESENT
  else echo "ABSENT"; fi
}
row(){ printf "  %-40s %s\n" "$2" "$(probe "$1")"; }

echo "# gfx-ISA capability map — arch=$ARCH  (llvm-mc ground truth)"
echo "## Matrix — WMMA (dense)"
row 'v_wmma_f32_16x16x16_f16 v[0:7], v[8:9], v[10:11], v[0:7]'        'v_wmma_f32_16x16x16_f16'
row 'v_wmma_f32_16x16x16_bf16 v[0:7], v[8:9], v[10:11], v[0:7]'       'v_wmma_f32_16x16x16_bf16'
row 'v_wmma_f32_16x16x16_fp8_fp8 v[0:7], v[8:9], v[10:11], v[0:7]'    'v_wmma_f32_16x16x16_fp8_fp8'
row 'v_wmma_f32_16x16x16_bf8_bf8 v[0:7], v[8:9], v[10:11], v[0:7]'    'v_wmma_f32_16x16x16_bf8_bf8'
row 'v_wmma_i32_16x16x16_iu8 v[0:7], v[8:9], v[10:11], v[0:7]'        'v_wmma_i32_16x16x16_iu8'
row 'v_wmma_i32_16x16x32_iu4 v[0:7], v[8:9], v[10:11], v[0:7]'        'v_wmma_i32_16x16x32_iu4'
echo "## Matrix — SWMMAC (2:4 structured sparse)"
row 'v_swmmac_f32_16x16x32_fp8_fp8 v[0:7], v[44:45], v[23:26], v17'   'v_swmmac_f32_16x16x32_fp8_fp8'
row 'v_swmmac_f32_16x16x32_f16 v[0:7], v[44:45], v[23:26], v17'       'v_swmmac_f32_16x16x32_f16'
row 'v_swmmac_i32_16x16x64_iu4 v[0:7], v[44:45], v[23:26], v17'       'v_swmmac_i32_16x16x64_iu4'
echo "## Dot (GEMV / decode levers)"
row 'v_dot8_i32_iu4 v0, v1, v2, v3'          'v_dot8_i32_iu4   (int4 dot8)'
row 'v_dot4_i32_iu8 v0, v1, v2, v3'          'v_dot4_i32_iu8   (dp4a int8)'
row 'v_dot4_f32_fp8_fp8 v0, v1, v2, v3'      'v_dot4_f32_fp8_fp8'
row 'v_dot2_f32_f16 v0, v1, v2, v3'          'v_dot2_f32_f16'
row 'v_dot2_f32_bf16 v0, v1, v2, v3'         'v_dot2_f32_bf16'
row 'v_dot2c_f32_f16 v0, v1, v2'             'v_dot2c_f32_f16  (dual-issue accum)'
echo "## Convert / scale (MX scale-unit check)"
row 'v_cvt_pk_fp8_f32 v0, v1, v2'                          'v_cvt_pk_fp8_f32   (plain, no scale)'
row 'v_cvt_pk_bf8_f32 v0, v1, v2'                          'v_cvt_pk_bf8_f32'
row 'v_cvt_scalef32_pk_fp8_f32 v0, v[1:2], v3'            'v_cvt_scalef32_pk_fp8_f32'
row 'v_cvt_scalef32_pk32_fp6_f16 v[0:5], v[6:21], v22'   'v_cvt_scalef32_pk32_fp6_f16'
row 'v_cvt_scalef32_2xpk16_fp6_f32 v[0:5], v[6:21], v[22:37], v38' 'v_cvt_scalef32_2xpk16_fp6_f32'
row 'v_cvt_sr_fp8_f32 v0, v1, v2'                          'v_cvt_sr_fp8_f32   (stochastic round)'
echo "## Packed VALU"
row 'v_pk_fma_f16 v0, v1, v2, v3'   'v_pk_fma_f16'
row 'v_pk_mul_f16 v0, v1, v2'       'v_pk_mul_f16'
echo ""
echo "# LEGEND: PRESENT=in silicon (usable); ABSENT=gated/other-arch (do NOT chase)."
echo "# NEXT: cross-ref PRESENT vs what your kernels emit (disasm-gfx.sh) => unexploited-HW list."
