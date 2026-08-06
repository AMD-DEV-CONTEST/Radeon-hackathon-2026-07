# vllm_rocm_ops.py — Safety net: Python fallbacks for missing vLLM _C operators
#
# IMPORTANT: After running rebuild_vllm_rocm.sh (source build), vllm._C is
# natively compiled for ROCm and this file is NOT needed. It is kept as a
# safety net for edge cases where some operators might still be missing.
#
# Historical context:
#   When vLLM was installed from PyPI (CUDA wheel), vllm._C was not available
#   on ROCm, causing: AttributeError: '_C' object has no attribute 'silu_and_mul'
#   This file registered Python fallbacks as a workaround. The correct fix is
#   building vLLM from source with PYTORCH_ROCM_ARCH=gfx1100.
#
# Loaded via:
#   sitecustomize.py (auto-imported by Python when scripts/ is on PYTHONPATH)
#
# Operators registered (used only if vllm._C operators are missing):
#   - silu_and_mul, gelu_and_mul, gelu_tanh_and_mul, gelu_fast_and_mul
#   - rms_norm, fused_add_rms_norm
#   - rotary_embedding
#   - reshape_and_cache, reshape_and_cache_flash
#   - copy_blocks

import torch
import torch.nn.functional as F
import math
import warnings

# Track registration results for diagnostics
_registered_ops = {}
_failed_ops = {}


def _op_exists(name):
    """Check if an operator already exists in torch.ops._C."""
    try:
        getattr(torch.ops._C, name)
        return True
    except (AttributeError, RuntimeError):
        return False


def _register_op(name, schema, impl_fn, fake_fn=None):
    """Register a custom operator in the _C namespace.

    Uses torch.library.define + impl + register_fake.
    Returns True on success, False on failure.
    """
    if _op_exists(name):
        _registered_ops[name] = "already exists"
        return True

    full_name = f"_C::{name}"

    try:
        torch.library.define(full_name, schema)

        # Register for CUDA (ROCm uses CUDA backend in PyTorch)
        torch.library.impl(full_name, "CUDA", impl_fn)
        # Register for CPU too (some ops may be called on CPU tensors)
        torch.library.impl(full_name, "CPU", impl_fn)

        # Register fake/meta implementation (needed for torch.compile)
        if fake_fn is not None:
            torch.library.register_fake(full_name, fake_fn)
        else:
            # Default fake impl: do nothing (for in-place mutating ops)
            torch.library.register_fake(full_name, lambda *a, **kw: None)

        _registered_ops[name] = "registered"
        return True
    except Exception as e:
        _failed_ops[name] = str(e)
        return False


# ============================================================
# Activation operators
# ============================================================

def _silu_and_mul_impl(x, out):
    """SiLU(x[..., :d]) * x[..., d:] -> out"""
    d = x.shape[-1] // 2
    out.copy_(F.silu(x[..., :d]) * x[..., d:])


def _gelu_and_mul_impl(x, out):
    """GELU(x[..., :d]) * x[..., d:] -> out"""
    d = x.shape[-1] // 2
    out.copy_(F.gelu(x[..., :d]) * x[..., d:])


def _gelu_tanh_and_mul_impl(x, out):
    """GELU(tanh)(x[..., :d]) * x[..., d:] -> out"""
    d = x.shape[-1] // 2
    out.copy_(F.gelu(x[..., :d], approximate="tanh") * x[..., d:])


def _gelu_fast_and_mul_impl(x, out):
    """Fast GELU(x[..., :d]) * x[..., d:] -> out"""
    d = x.shape[-1] // 2
    gate = x[..., :d]
    # Fast GELU: x * sigmoid(1.702 * x)
    out.copy_(gate * torch.sigmoid(1.702 * gate) * x[..., d:])


# ============================================================
# Normalization operators
# ============================================================

def _rms_norm_impl(output, input, weight, epsilon):
    """RMS normalization: output = input / sqrt(mean(input^2) + eps) * weight

    NOTE: Argument order matches vLLM's C++ operator call:
      torch.ops._C.rms_norm(output, x, weight, epsilon)
    output is FIRST (mutated), not last.
    """
    variance = input.pow(2).mean(-1, keepdim=True)
    input_normed = input * torch.rsqrt(variance + epsilon)
    output.copy_(input_normed * weight)


def _fused_add_rms_norm_impl(x, x_residual, weight, epsilon):
    """Fused residual add + RMS normalization (in-place).

    Modifies x and x_residual in-place:
      x_residual = x + x_residual  (residual sum)
      x = rms_norm(x_residual, weight, epsilon)  (normalized output)

    NOTE: Argument order matches vLLM's C++ operator call:
      torch.ops._C.fused_add_rms_norm(x, x_residual, weight, epsilon)
    Both x and x_residual are mutated in-place (no separate output args).
    """
    # Step 1: x_residual = x + x_residual (uses original x)
    x_residual.add_(x)
    # Step 2: x = rms_norm(x_residual, weight, epsilon)
    variance = x_residual.pow(2).mean(-1, keepdim=True)
    x_normed = x_residual * torch.rsqrt(variance + epsilon)
    x.copy_(x_normed * weight)


# ============================================================
# Rotary embedding operator
# ============================================================

def _rotary_embedding_impl(positions, query, key, head_size, cos_sin_cache, is_neox):
    """Apply rotary position embedding to query and key tensors.

    Args:
        positions: [batch_size, seq_len] position indices
        query: [batch_size, seq_len, num_heads, head_size] query tensor
        key: [batch_size, seq_len, num_kv_heads, head_size] key tensor
        head_size: int, size of each attention head
        cos_sin_cache: [max_position, 2, head_size // 2] cos/sin cache
        is_neox: bool, whether to use NeoX-style rotation
    """
    batch_size, seq_len, num_heads_q, _ = query.shape
    num_heads_k = key.shape[2]
    rot_dim = cos_sin_cache.shape[2] * 2  # head_size // 2 * 2

    # Flatten positions for indexing
    pos_flat = positions.reshape(-1).long()
    cos_sin = cos_sin_cache.index_select(0, pos_flat)
    cos = cos_sin[:, 0].unsqueeze(1).unsqueeze(1)  # [batch*seq, 1, 1, head_size//2]
    sin = cos_sin[:, 1].unsqueeze(1).unsqueeze(1)

    # Reshape query and key for rotation
    q_rot = query[..., :rot_dim].reshape(
        batch_size * seq_len, num_heads_q, rot_dim // 2, 2
    )
    k_rot = key[..., :rot_dim].reshape(
        batch_size * seq_len, num_heads_k, rot_dim // 2, 2
    )

    if is_neox:
        # NeoX style: [..., 0::2] and [..., 1::2]
        q1 = q_rot[..., 0]
        q2 = q_rot[..., 1]
        k1 = k_rot[..., 0]
        k2 = k_rot[..., 1]
    else:
        # GPT-J style: [..., :half] and [..., half:]
        half = rot_dim // 2
        q1 = q_rot[..., :half // 2].reshape(
            batch_size * seq_len, num_heads_q, half // 2
        )
        q2 = q_rot[..., half // 2:].reshape(
            batch_size * seq_len, num_heads_q, half // 2
        )
        k1 = k_rot[..., :half // 2].reshape(
            batch_size * seq_len, num_heads_k, half // 2
        )
        k2 = k_rot[..., half // 2:].reshape(
            batch_size * seq_len, num_heads_k, half // 2
        )

    # Apply rotation
    q_rotated = torch.stack([
        q1 * cos.squeeze(1) - q2 * sin.squeeze(1),
        q1 * sin.squeeze(1) + q2 * cos.squeeze(1),
    ], dim=-1).reshape(batch_size, seq_len, num_heads_q, rot_dim)

    k_rotated = torch.stack([
        k1 * cos.squeeze(1) - k2 * sin.squeeze(1),
        k1 * sin.squeeze(1) + k2 * cos.squeeze(1),
    ], dim=-1).reshape(batch_size, seq_len, num_heads_k, rot_dim)

    # Copy rotated parts back
    query[..., :rot_dim].copy_(q_rotated)
    key[..., :rot_dim].copy_(k_rotated)


# ============================================================
# KV cache operators
# ============================================================

def _reshape_and_cache_impl(key, value, key_cache, value_cache, slot_mapping):
    """Reshape and cache key/value tensors into paged KV cache.

    Args:
        key: [num_tokens, num_heads, head_size] new key tokens
        value: [num_tokens, num_heads, head_size] new value tokens
        key_cache: [num_blocks, block_size, num_heads, head_size] cache
        value_cache: [num_blocks, block_size, num_heads, head_size] cache
        slot_mapping: [num_tokens] flat slot indices into cache
    """
    slot_mapping = slot_mapping.long()
    block_size = key_cache.shape[1]

    # Compute block indices and offsets
    block_indices = slot_mapping // block_size
    block_offsets = slot_mapping % block_size

    # Write key and value into cache
    key_cache.index_put_(
        (block_indices, block_offsets), key, accumulate=False
    )
    value_cache.index_put_(
        (block_indices, block_offsets), value, accumulate=False
    )


def _reshape_and_cache_flash_impl(key, value, key_cache, value_cache,
                                   slot_mapping, kv_cache_dtype):
    """Flash attention version of reshape_and_cache.

    Similar to reshape_and_cache but with additional kv_cache_dtype parameter.
    """
    _reshape_and_cache_impl(key, value, key_cache, value_cache, slot_mapping)


# ============================================================
# Copy blocks operator (for beam search / parallel decoding)
# ============================================================

def _copy_blocks_impl(key_caches, value_caches, block_mapping):
    """Copy blocks within KV cache for beam search.

    Args:
        key_caches: list of key cache tensors
        value_caches: list of value cache tensors
        block_mapping: [num_mappings, 2] tensor of (src, dst) block indices
    """
    for i in range(len(key_caches)):
        for src, dst in block_mapping:
            key_caches[i][dst].copy_(key_caches[i][src])
            value_caches[i][dst].copy_(value_caches[i][src])


# ============================================================
# Register all operators
# ============================================================

def register_all_ops():
    """Register all missing _C operators. Call this at module import time."""

    # --- Activation operators ---
    _register_op(
        "silu_and_mul",
        "(Tensor x, Tensor(!) out) -> ()",
        _silu_and_mul_impl,
    )
    _register_op(
        "gelu_and_mul",
        "(Tensor x, Tensor(!) out) -> ()",
        _gelu_and_mul_impl,
    )
    _register_op(
        "gelu_tanh_and_mul",
        "(Tensor x, Tensor(!) out) -> ()",
        _gelu_tanh_and_mul_impl,
    )
    _register_op(
        "gelu_fast_and_mul",
        "(Tensor x, Tensor(!) out) -> ()",
        _gelu_fast_and_mul_impl,
    )

    # --- Normalization operators ---
    # NOTE: Schema argument order MUST match vLLM's C++ operator calls:
    #   torch.ops._C.rms_norm(output, x, weight, epsilon)         — output FIRST
    #   torch.ops._C.fused_add_rms_norm(x, x_residual, weight, epsilon) — in-place
    _register_op(
        "rms_norm",
        "(Tensor(!) output, Tensor input, Tensor weight, float epsilon) -> ()",
        _rms_norm_impl,
    )
    _register_op(
        "fused_add_rms_norm",
        "(Tensor(!) x, Tensor(!) x_residual, Tensor weight, float epsilon) -> ()",
        _fused_add_rms_norm_impl,
    )

    # --- Rotary embedding ---
    _register_op(
        "rotary_embedding",
        "(Tensor positions, Tensor(a!) query, Tensor(b!) key, "
        "int head_size, Tensor cos_sin_cache, bool is_neox) -> ()",
        _rotary_embedding_impl,
    )

    # --- KV cache operators ---
    _register_op(
        "reshape_and_cache",
        "(Tensor key, Tensor value, Tensor(a!) key_cache, "
        "Tensor(b!) value_cache, Tensor slot_mapping) -> ()",
        _reshape_and_cache_impl,
    )
    _register_op(
        "reshape_and_cache_flash",
        "(Tensor key, Tensor value, Tensor(a!) key_cache, "
        "Tensor(b!) value_cache, Tensor slot_mapping, "
        "str kv_cache_dtype) -> ()",
        _reshape_and_cache_flash_impl,
    )

    # --- Copy blocks ---
    _register_op(
        "copy_blocks",
        "(Tensor[] key_caches, Tensor[] value_caches, Tensor block_mapping) -> ()",
        _copy_blocks_impl,
    )


# ============================================================
# Run registration
# ============================================================

register_all_ops()

# Print summary (only in main process to avoid spam in child processes)
if __name__ != "__main__" and torch.cuda.is_available():
    _ok = len(_registered_ops)
    _fail = len(_failed_ops)
    if _ok > 0:
        # Only print in the main process (not EngineCore workers)
        import os
        if os.environ.get("VLLM_ROCM_OPS_DEBUG", "0") == "1":
            print(f"[vllm_rocm_ops] Registered {_ok} operators, {_fail} failed")
            for name, status in _registered_ops.items():
                print(f"  [OK] _C::{name} ({status})")
            for name, err in _failed_ops.items():
                print(f"  [FAIL] _C::{name}: {err}")
else:
    # When run directly, print full report
    print(f"[vllm_rocm_ops] Registration summary:")
    print(f"  Success: {len(_registered_ops)}")
    print(f"  Failed:  {len(_failed_ops)}")
    for name, status in sorted(_registered_ops.items()):
        print(f"  [OK] _C::{name} ({status})")
    for name, err in sorted(_failed_ops.items()):
        print(f"  [FAIL] _C::{name}: {err}")

    if _failed_ops:
        print("\n[WARNING] Some operators failed to register.")
        print("vLLM may still crash when accessing these operators.")
        print("Run: python scripts/patch_vllm_source.py")
        print("This will patch vLLM source files as a fallback.")
