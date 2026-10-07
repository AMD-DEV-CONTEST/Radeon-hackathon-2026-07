"""Local ROCm compatibility patch for lerobot's resize_with_pad.

This module monkey-patches `lerobot.policies.smolvla.modeling_smolvla.resize_with_pad`
to add an explicit uint8->float32 cast before `F.interpolate(mode='bilinear')`,
which raises `NotImplementedError` on the AMD ROCm backend.

This patch is applied automatically when `eval_sort_smolvla_robust.py` (or
any module that imports this shim) is loaded. It is a no-op on CUDA (the
cast is harmless -- the image is already float32 by the time it reaches
resize_with_pad in normal inference, and float32 bilinear works on both
backends).

Upstream Issue: https://github.com/huggingface/lerobot/issues/4205
Upstream PR: (pending submission)
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


def _patched_resize_with_pad(
    img: torch.Tensor, width: int, height: int, pad_value: float = -1
) -> torch.Tensor:
    """Patched resize_with_pad with uint8->float32 cast for ROCm compatibility.

    Identical to the upstream function except for the dtype guard marked
    `# [ROCm fix]` below.

    Note: In lerobot 0.6.0, the signature is (img, width, height, pad_value=-1),
    different from the old (img, height, width, *, pad_value).
    """
    if img.ndim != 4:
        raise ValueError(f"(b,c,h,w) expected, but got {img.shape}")

    current_height, current_width = img.shape[2:]
    if current_height == height and current_width == width:
        return img

    # ------------------------------------------------------------------
    # [ROCm fix] Cast uint8 to float32 before F.interpolate.
    #
    # PyTorch's ROCm backend does not ship a uint8 bilinear-interpolation
    # kernel, so F.interpolate(mode='bilinear') raises NotImplementedError
    # when the input dtype is torch.uint8. CUDA does ship such a kernel,
    # which is why this bug only manifests on AMD GPUs.
    # ------------------------------------------------------------------
    original_dtype = img.dtype
    if original_dtype == torch.uint8:
        img = img.to(dtype=torch.float32)
    # [end ROCm fix]

    ratio = max(current_width / width, current_height / height)
    resized_height = int(current_height / ratio)
    resized_width = int(current_width / ratio)
    resized_img = F.interpolate(
        img, size=(resized_height, resized_width), mode="bilinear", align_corners=False
    )

    pad_height = max(0, height - resized_height)
    pad_width = max(0, width - resized_width)
    padded_img = F.pad(resized_img, (pad_width, 0, pad_height, 0), value=pad_value)
    return padded_img


def apply_patch() -> bool:
    """Monkey-patch resize_with_pad in the lerobot package.

    Returns:
        True if the patch was applied, False if lerobot is not installed
        or the target function could not be found.
    """
    # lerobot 0.6.0: resize_with_pad is a module-level function in
    # lerobot.policies.smolvla.modeling_smolvla
    try:
        from lerobot.policies.smolvla import modeling_smolvla as _ms

        if hasattr(_ms, "resize_with_pad"):
            _ms.resize_with_pad = _patched_resize_with_pad
            print(
                "[roc_patch] Patched lerobot.policies.smolvla.modeling_smolvla.resize_with_pad"
            )
            return True
    except ImportError:
        pass

    # Fallback: try legacy paths for older lerobot versions
    try:
        from lerobot.policies.common import vla_utils as _vu

        if hasattr(_vu, "resize_with_pad"):
            _vu.resize_with_pad = _patched_resize_with_pad
            print(
                "[roc_patch] Patched lerobot.policies.common.vla_utils.resize_with_pad"
            )
            return True
    except ImportError:
        pass

    try:
        from lerobot.common.policies import vla_utils as _vu

        if hasattr(_vu, "resize_with_pad"):
            _vu.resize_with_pad = _patched_resize_with_pad
            print(
                "[roc_patch] Patched lerobot.common.policies.vla_utils.resize_with_pad"
            )
            return True
    except ImportError:
        pass

    print(
        "[roc_patch] WARNING: Could not locate resize_with_pad in lerobot; patch not applied."
    )
    return False


# Auto-apply on import
apply_patch()
