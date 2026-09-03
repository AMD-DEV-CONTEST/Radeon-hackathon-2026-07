# gfx-ISA capability map — arch=gfx1201  (llvm-mc ground truth)
## Matrix — WMMA (dense)
  v_wmma_f32_16x16x16_f16                  PRESENT
  v_wmma_f32_16x16x16_bf16                 PRESENT
  v_wmma_f32_16x16x16_fp8_fp8              PRESENT
  v_wmma_f32_16x16x16_bf8_bf8              PRESENT
  v_wmma_i32_16x16x16_iu8                  PRESENT
  v_wmma_i32_16x16x32_iu4                  PRESENT
## Matrix — SWMMAC (2:4 structured sparse)
  v_swmmac_f32_16x16x32_fp8_fp8            PRESENT
  v_swmmac_f32_16x16x32_f16                PRESENT
  v_swmmac_i32_16x16x64_iu4                PRESENT
## Dot (GEMV / decode levers)
  v_dot8_i32_iu4   (int4 dot8)             PRESENT
  v_dot4_i32_iu8   (dp4a int8)             PRESENT
  v_dot4_f32_fp8_fp8                       PRESENT
  v_dot2_f32_f16                           PRESENT
  v_dot2_f32_bf16                          PRESENT
  v_dot2c_f32_f16  (dual-issue accum)      ABSENT
## Convert / scale (MX scale-unit check)
  v_cvt_pk_fp8_f32   (plain, no scale)     PRESENT
  v_cvt_pk_bf8_f32                         PRESENT
  v_cvt_scalef32_pk_fp8_f32                ABSENT
  v_cvt_scalef32_pk32_fp6_f16              ABSENT
  v_cvt_scalef32_2xpk16_fp6_f32            ABSENT
  v_cvt_sr_fp8_f32   (stochastic round)    PRESENT
## Packed VALU
  v_pk_fma_f16                             PRESENT
  v_pk_mul_f16                             PRESENT

# LEGEND: PRESENT=in silicon (usable); ABSENT=gated/other-arch (do NOT chase).
# NEXT: cross-ref PRESENT vs what your kernels emit (disasm-gfx.sh) => unexploited-HW list.
