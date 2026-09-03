"""
MXFP6 (E3M2, OCP MX FP6) numpy reference codec -- for the JM decode-weight
scope addition (INT6 vs MXFP6 head-to-head on real weights).

Vectorized numpy re-implementation, kept bit-for-bit faithful to the C
reference (mainline-llama.cpp-mxfp8 fork):
  ggml/src/ggml-quants.c: quantize_row_mxfp6_ref / dequantize_row_mxfp6
  ggml/src/ggml-impl.h:   ggml_fp32_to_e3m2 / ggml_e3m2_to_fp32 / ggml_e8m0_to_fp32
Format: block-32, one shared UE8M0 (biased-127, power-of-2-only) scale byte
per block + 32 six-bit E3M2 codes (1 sign, 3 exp bits bias=3, 2 mantissa
bits, NO Inf/NaN -- all 64 patterns finite, max finite magnitude 28.0).
"""
import numpy as np

QK_MXFP6 = 32


def _e8m0_to_fp32(e: np.ndarray) -> np.ndarray:
    """UE8M0: value = 2^(e-127), e=0 -> denormal 2^-127 special-case per C ref."""
    e = e.astype(np.int64)
    out = np.exp2((e - 127).astype(np.float64)).astype(np.float32)
    out = np.where(e == 0, np.float32(2.0 ** -127), out)
    return out


def _fp32_to_e8m0_biased_for_amax_over_28(amax: np.ndarray) -> np.ndarray:
    """Smallest power-of-two scale d=2^e such that amax/d <= 28.0 (E3M2 max
    finite). Mirrors quantize_row_mxfp6_ref's frexpf(amax/28, &exp2) logic."""
    amax = amax.astype(np.float64)
    ratio = amax / 28.0
    biased = np.zeros_like(amax, dtype=np.int64)
    nz = amax > 0
    r = ratio[nz]
    mant, exp2 = np.frexp(r)  # r = mant * 2^exp2, 0.5 <= mant < 1 (mant==0 handled by nz)
    b = np.where(mant <= 0.5, exp2 - 1 + 127, exp2 + 127)
    b = np.clip(b, 0, 254)
    biased[nz] = b
    return biased.astype(np.uint8)


def _fp32_to_e3m2(x: np.ndarray) -> np.ndarray:
    """Vectorized bit-exact port of ggml_fp32_to_e3m2 (ggml-impl.h)."""
    x = x.astype(np.float32)
    bits = x.view(np.uint32)
    sign = (bits >> 31) & 1

    ax = np.abs(x).astype(np.float32)
    ax = np.where(np.isnan(x), np.float32(28.0), ax)
    ax = np.minimum(ax, np.float32(28.0))

    axbits = ax.view(np.uint32)
    fp32_exp = ((axbits >> 23) & 0xFF).astype(np.int64) - 127
    fp32_man = ((axbits >> 21) & 0x3).astype(np.int64)
    round_bit = ((axbits >> 20) & 1).astype(np.int64)
    e3_exp = fp32_exp + 3

    # subnormal branch (e3_exp <= 0): man = (int)(ax*16+0.5) -- C truncating
    # cast, NOT round-half-to-even, so np.floor (not np.round) is required to
    # match bit-for-bit (verified: np.round(1.5)=2 via banker's rounding vs
    # C (int)(1.5f)=1 -- this mismatch was caught by the idempotency self-test
    # below before shipping).
    man_sub = np.floor(ax.astype(np.float64) * 16.0 + 0.5).astype(np.int64)
    man_sub = np.clip(man_sub, 0, 3)  # (C clips only upper bound to 3; man<1 -> zero code below)

    # normal branch
    e3_man = fp32_man + round_bit
    overflow_man = e3_man > 3
    e3_man = np.where(overflow_man, 0, e3_man)
    e3_exp_n = np.where(overflow_man, e3_exp + 1, e3_exp)
    clamp_exp = e3_exp_n > 7
    e3_exp_n = np.where(clamp_exp, 7, e3_exp_n)
    e3_man = np.where(clamp_exp, 3, e3_man)

    code_normal = ((sign.astype(np.int64) << 5) | (e3_exp_n << 2) | e3_man).astype(np.uint8)
    code_sub_nonzero = ((sign.astype(np.int64) << 5) | man_sub).astype(np.uint8)
    code_sub_zero = (sign.astype(np.int64) << 5).astype(np.uint8)

    is_zero_input = ~(ax > 0)
    is_sub = (e3_exp <= 0) & ~is_zero_input
    is_sub_but_zero = is_sub & (man_sub < 1)

    code = np.where(is_zero_input, code_sub_zero,
             np.where(is_sub_but_zero, code_sub_zero,
               np.where(is_sub, code_sub_nonzero, code_normal)))
    return code.astype(np.uint8)


def _e3m2_to_fp32(code: np.ndarray) -> np.ndarray:
    code = code.astype(np.int64)
    sign = (code >> 5) & 1
    exp3 = (code >> 2) & 0x7
    man2 = code & 0x3
    normal = np.exp2((exp3 - 3).astype(np.float64)) * (1.0 + man2 / 4.0)
    sub = man2 * (2.0 ** -4)
    val = np.where(exp3 == 0, sub, normal)
    val = np.where(sign == 1, -val, val)
    return val.astype(np.float32)


def quantize_mxfp6(x: np.ndarray, block: int = QK_MXFP6):
    """x: float array, last axis = pack axis. Returns (e8m0_scale[..., nblk]
    uint8, codes[..., nblk, block] uint8 raw E3M2, orig_shape, pad)."""
    x = np.asarray(x, dtype=np.float32)
    orig_shape = x.shape
    n = orig_shape[-1]
    pad = (-n) % block
    if pad:
        x = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(0, pad)])
    nblk = x.shape[-1] // block
    xb = x.reshape(*x.shape[:-1], nblk, block)

    amax = np.max(np.abs(xb), axis=-1)
    e = _fp32_to_e8m0_biased_for_amax_over_28(amax)
    d = _e8m0_to_fp32(e)
    id_ = np.where(d > 0, 1.0 / d, 0.0).astype(np.float32)

    x0 = xb * id_[..., None]
    codes = _fp32_to_e3m2(x0)
    return e, codes, orig_shape, pad


def dequantize_mxfp6(e: np.ndarray, codes: np.ndarray, orig_shape, pad: int):
    d = _e8m0_to_fp32(e)
    vals = _e3m2_to_fp32(codes) * d[..., None]
    x = vals.reshape(*e.shape[:-1], -1)
    if pad:
        x = x[..., :orig_shape[-1]]
    return x.reshape(orig_shape)


def round_trip_mxfp6(x: np.ndarray, block: int = QK_MXFP6):
    e, codes, orig_shape, pad = quantize_mxfp6(x, block)
    return dequantize_mxfp6(e, codes, orig_shape, pad)


def bytes_per_element(block: int = QK_MXFP6) -> float:
    return (1 + block * 6 / 8) / block  # 25 bytes / 32 vals = 6.25 bpw = 0.78125 B/elem
