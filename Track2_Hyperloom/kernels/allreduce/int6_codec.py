"""
INT6 symmetric block-32 codec -- numpy reference (T188).

CPU-only reference implementation for the QuickReduce-style inline-compressed
all-reduce codec. Mirrors ggml's block_mxfp6 bit-packing layout (4 values
packed per 3 bytes, see ggml-common.h block_mxfp6 / common.cuh
mxfp6_unpack4 in the mainline-llama.cpp-mxfp8 fork) so the same packing
convention is reused for an INTEGER (not float) 6-bit payload.

Codec family here supports bits in {4, 6, 8} block-32, symmetric, FP16
per-block scale -- used both as:
  (a) the all-reduce activation codec (exact-reduce property matters), and
  (b) a weight-quant comparison point against MXFP6 (E3M2) for the JM
      decode-weight scope addition (exact-reduce does NOT apply to weights).

Two's-complement packing: a signed value v in [-(2^(b-1)), 2^(b-1)-1] is
stored as the raw (v & mask) bit pattern, unpacked via sign-extension.
"""
import numpy as np

QK = 32  # block size, matches ggml convention (QK4_0/QK_MXFP6/QK8_0 all 32)


def _bits_meta(bits: int):
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    mask = (1 << bits) - 1
    return lo, hi, mask


def quantize_codes(x: np.ndarray, bits: int, block: int = QK):
    """Symmetric per-block quantization to signed integer codes.

    x: float32/float16 array, last axis is the reduction/pack axis.
    Returns (scale[..., nblk] float32, codes[..., nblk, block] int32) --
    codes are UNPACKED (one int per element) for numeric testing; use
    pack_bits() to get the on-wire byte layout.
    """
    x = np.asarray(x, dtype=np.float32)
    orig_shape = x.shape
    n = orig_shape[-1]
    pad = (-n) % block
    if pad:
        x = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(0, pad)])
    nblk = x.shape[-1] // block
    xb = x.reshape(*x.shape[:-1], nblk, block)

    lo, hi, _mask = _bits_meta(bits)
    absmax = np.max(np.abs(xb), axis=-1)                      # [..., nblk]
    scale = (absmax / hi).astype(np.float32)
    scale_safe = np.where(scale == 0, 1.0, scale)

    codes = np.round(xb / scale_safe[..., None])
    codes = np.clip(codes, lo, hi).astype(np.int32)
    scale = np.where(np.max(np.abs(xb), axis=-1) == 0, 0.0, scale)
    return scale, codes, orig_shape, pad


def dequantize_codes(scale: np.ndarray, codes: np.ndarray, orig_shape, pad: int):
    x = (codes.astype(np.float32) * scale[..., None]).reshape(*scale.shape[:-1], -1)
    if pad:
        x = x[..., :orig_shape[-1]]
    return x.reshape(orig_shape)


def pack_bits(codes: np.ndarray, bits: int) -> np.ndarray:
    """Pack a [..., nblk, block] int array of signed codes into raw bytes.

    bits=6: 4 values per 3 bytes, IDENTICAL bit layout to ggml block_mxfp6
    (mxfp6_unpack4 / pack_mxfp6_preserve, mainline-llama.cpp-mxfp8):
        combined = v0 | (v1<<6) | (v2<<12) | (v3<<18)
        byte0 = combined>>16, byte1 = combined>>8, byte2 = combined
        stored order per group-of-4: [byte2, byte1, byte0]  (qs[3g+0..2])
    bits=4: 2 values per byte (lo nibble first, matches ggml q4_0 convention).
    bits=8: 1 value per byte (raw two's complement, matches q8_0).
    """
    _lo, _hi, mask = _bits_meta(bits)
    block = codes.shape[-1]
    u = (codes & mask).astype(np.uint32)                      # raw bit pattern

    if bits == 8:
        return u.astype(np.uint8)

    if bits == 4:
        assert block % 2 == 0
        u2 = u.reshape(*u.shape[:-1], block // 2, 2)
        packed = (u2[..., 0] | (u2[..., 1] << 4)).astype(np.uint8)
        return packed

    if bits == 6:
        assert block % 4 == 0
        u4 = u.reshape(*u.shape[:-1], block // 4, 4)
        v0, v1, v2, v3 = u4[..., 0], u4[..., 1], u4[..., 2], u4[..., 3]
        combined = (v0 | (v1 << 6) | (v2 << 12) | (v3 << 18)).astype(np.uint32)
        b0 = (combined & 0xFF).astype(np.uint8)
        b1 = ((combined >> 8) & 0xFF).astype(np.uint8)
        b2 = ((combined >> 16) & 0xFF).astype(np.uint8)
        # ggml qs[3g+0..2] order per mxfp6_unpack4: qs3[0]=b0, qs3[1]=b1, qs3[2]=b2
        out = np.stack([b0, b1, b2], axis=-1)                 # [..., nblk_of_4, 3]
        return out.reshape(*out.shape[:-2], out.shape[-2] * 3)

    raise ValueError(f"unsupported bits={bits}")


def unpack_bits(packed: np.ndarray, bits: int, block: int) -> np.ndarray:
    """Inverse of pack_bits -> signed two's-complement codes [..., nblk, block]."""
    lo, hi, mask = _bits_meta(bits)
    sign_bit = 1 << (bits - 1)

    def sign_extend(u):
        u = u.astype(np.int32)
        return np.where(u & sign_bit, u - (1 << bits), u)

    if bits == 8:
        return sign_extend(packed.astype(np.uint8))

    if bits == 4:
        lo_n = packed & 0x0F
        hi_n = (packed >> 4) & 0x0F
        u = np.stack([lo_n, hi_n], axis=-1)
        u = u.reshape(*u.shape[:-2], u.shape[-2] * 2)
        return sign_extend(u)

    if bits == 6:
        nblk4 = packed.shape[-1] // 3
        g = packed.reshape(*packed.shape[:-1][:], nblk4, 3).astype(np.uint32)
        b0, b1, b2 = g[..., 0], g[..., 1], g[..., 2]
        v0 = b0 & 0x3F
        v1 = ((b0 >> 6) & 0x03) | ((b1 & 0x0F) << 2)
        v2 = ((b1 >> 4) & 0x0F) | ((b2 & 0x03) << 4)
        v3 = (b2 >> 2) & 0x3F
        u = np.stack([v0, v1, v2, v3], axis=-1)
        u = u.reshape(*u.shape[:-2], u.shape[-2] * 4)
        return sign_extend(u)

    raise ValueError(f"unsupported bits={bits}")


def pack(x: np.ndarray, bits: int, block: int = QK):
    """Full pack: float -> (scale_fp16, packed_bytes, orig_shape, pad)."""
    scale, codes, orig_shape, pad = quantize_codes(x, bits, block)
    packed = pack_bits(codes, bits)
    return scale.astype(np.float16), packed, orig_shape, pad


def unpack(scale: np.ndarray, packed: np.ndarray, bits: int, orig_shape, pad: int,
           block: int = QK):
    codes = unpack_bits(packed, bits, block)
    return dequantize_codes(scale.astype(np.float32), codes, orig_shape, pad)


def round_trip(x: np.ndarray, bits: int, block: int = QK):
    scale, packed, orig_shape, pad = pack(x, bits, block)
    y = unpack(scale, packed, bits, orig_shape, pad, block)
    return y


def bytes_per_element(bits: int, block: int = QK) -> float:
    """FP16 scale (2B) + block*bits/8 packed bytes, amortized per element."""
    return (2 + block * bits / 8) / block
