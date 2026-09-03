// quant_common.h — shared definitions for the quant-format agent-reproduction rig.
//
// Layouts and decode rules are taken from the roc8 fork (ggml-common.h for the
// structs, mul_mat_q2_0_gemv.cuh for the low-bit conventions, ggml-quants.c for
// the CPU dequantisers). They are not re-derived here.
//
//   Q1_0  QK=128 qs[16]  1 bit   bit k%8 of byte k/8; set -> +1, clear -> -1
//   Q2_0  QK=128 qs[32]  2 bits  code=(byte>>2*(k%4))&3 -> value code-1
//   Q4_0  QK=32  qs[16]  nibble  low nibble of byte j = elem j,
//                                high nibble of byte j = elem j+16; value n-8
//   Q8_0  QK=32  qs[32]  int8    value = qs[k] directly
//
// Compile with -DFMT_Q1 / -DFMT_Q2 / -DFMT_Q4 / -DFMT_Q8.

#pragma once
#include <hip/hip_runtime.h>
#include <hip/hip_fp16.h>
#include <cstdint>

#if   defined(FMT_Q1)
  #define FMT_NAME "Q1_0"
  #define QK_LOWBIT 128
  #define QS_BYTES  16
  typedef uint8_t qs_t;
#elif defined(FMT_Q2)
  #define FMT_NAME "Q2_0"
  #define QK_LOWBIT 128
  #define QS_BYTES  32
  typedef uint8_t qs_t;
#elif defined(FMT_Q4)
  #define FMT_NAME "Q4_0"
  #define QK_LOWBIT 32
  #define QS_BYTES  16
  typedef uint8_t qs_t;
#elif defined(FMT_Q8)
  #define FMT_NAME "Q8_0"
  #define QK_LOWBIT 32
  #define QS_BYTES  32
  typedef int8_t  qs_t;
#elif defined(FMT_Q5)
  #define FMT_NAME "Q5_0"
  #define QK_LOWBIT 32
  #define QS_BYTES  16
  #define HAS_QH    1
  typedef uint8_t qs_t;
#elif defined(FMT_MXFP4)
  #define FMT_NAME "MXFP4"
  #define QK_LOWBIT 32
  #define QS_BYTES  16
  #define E8M0_SCALE 1
  typedef uint8_t qs_t;
#elif defined(FMT_MXFP8)
  #define FMT_NAME "MXFP8"
  #define QK_LOWBIT 32
  #define QS_BYTES  32
  #define E8M0_SCALE 1
  typedef uint8_t qs_t;
#else
  #error "define FMT_Q1/Q2/Q4/Q5/Q8/MXFP4/MXFP8"
#endif

struct block_lowbit {
#if defined(E8M0_SCALE)
    uint8_t e;                 // UE8M0 shared scale: value = 2^(e-127)
#else
    __half  d;                 // continuous fp16 per-block scale
#endif
#if defined(HAS_QH)
    uint8_t qh[4];             // Q5_0: the 5th bit of each quant
#endif
    qs_t    qs[QS_BYTES];
};

// Per-block scale as a float, whichever encoding this format uses.
__host__ __device__ __forceinline__ float block_scale(const block_lowbit& b)
{
#if defined(E8M0_SCALE)
    return ldexpf(1.0f, (int)b.e - 127);       // 2^(e-127)
#else
    return __half2float(b.d);
#endif
}

// OCP E4M3 leaf decode (used by MXFP8): 1 sign / 4 exp / 3 mantissa, bias 7.
__host__ __device__ __forceinline__ float e4m3_leaf(uint8_t v)
{
    const int s = (v >> 7) & 1, e = (v >> 3) & 0xF, m = v & 0x7;
    const float sign = s ? -1.0f : 1.0f;
    if (e == 0)            return sign * ldexpf((float)m / 8.0f, -6);
    if (e == 15 && m == 7) return sign * 0.0f;      // NaN slot; never generated here
    return sign * ldexpf(1.0f + (float)m / 8.0f, e - 7);
}

// OCP E2M1 leaf decode (used by MXFP4): 1 sign / 2 exp / 1 mantissa, bias 1.
__host__ __device__ __forceinline__ float e2m1_leaf(uint8_t n)
{
    const int s = (n >> 3) & 1, e = (n >> 1) & 0x3, m = n & 0x1;
    const float sign = s ? -1.0f : 1.0f;
    if (e == 0) return sign * (m ? 0.5f : 0.0f);    // subnormal: 0 or 0.5
    return sign * ldexpf(1.0f + (float)m / 2.0f, e - 1);
}

// Decode element k (0..QK_LOWBIT-1) of a block to its logical value.
__host__ __device__ __forceinline__ float lowbit_value(const qs_t* qs, int k)
{
#if   defined(FMT_Q1)
    return ((qs[k / 8] >> (k % 8)) & 1) ? 1.0f : -1.0f;
#elif defined(FMT_Q2)
    const int code = (qs[k / 4] >> (2 * (k % 4))) & 3;
    return (float)(code - 1);                       // 0->-1, 1->0, 2->+1
#elif defined(FMT_Q4)
    const int j = k % 16;
    const int n = (k < 16) ? (qs[j] & 0x0F) : (qs[j] >> 4);
    return (float)(n - 8);                          // unsigned 0..15 -> -8..+7
#elif defined(FMT_Q5)
    const int j = k % 16;
    const int lo = (k < 16) ? (qs[j] & 0x0F) : (qs[j] >> 4);
    return (float)(lo - 16);                 // 5th bit added by caller
#elif defined(FMT_MXFP4)
    const int j = k % 16;
    const int n = (k < 16) ? (qs[j] & 0x0F) : (qs[j] >> 4);
    return e2m1_leaf((uint8_t)n);
#elif defined(FMT_MXFP8)
    return e4m3_leaf(qs[k]);
#else   // FMT_Q8
    return (float)qs[k];
#endif
}

// Seed a block's scale with the convention this format uses.
__host__ __forceinline__ void set_block_scale(block_lowbit& b)
{
#if defined(E8M0_SCALE)
    b.e = 127;                     // 2^(127-127) = 1.0
#else
    b.d = __float2half(0.02f);
#endif
}
