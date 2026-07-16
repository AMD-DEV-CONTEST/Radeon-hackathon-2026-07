"""Compute device detection (ROCm / CUDA / CPU).

ROCm on PyTorch exposes itself through the `torch.cuda.*` API but it is
**not** NVIDIA CUDA — the only way to tell them apart is `torch.version.hip`
vs `torch.version.cuda`. This module hides that detail so the rest of the
codebase just calls `get_device()` and gets back a clean `"cuda"` string.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

log = logging.getLogger(__name__)

# We expose ROCm as a "kind" for logging / branching, but PyTorch still uses
# the "cuda" device string for both ROCm and CUDA backends.
DeviceKind = Literal["rocm", "cuda", "cpu"]


def detect_device_kind() -> DeviceKind:
    """Detect the active compute device kind by probing PyTorch.

    Returns:
        "rocm"  - AMD GPU via ROCm
        "cuda"  - NVIDIA GPU via CUDA
        "cpu"   - no GPU available
    """
    import torch  # imported here to keep this module importable without torch

    if not torch.cuda.is_available():
        return "cpu"

    # ROCm sets torch.version.hip; CUDA sets torch.version.cuda.
    if torch.version.hip is not None:
        return "rocm"
    if torch.version.cuda is not None:
        return "cuda"

    # Defensive fallback: torch says GPU is available but no backend reported.
    log.warning("torch.cuda.is_available() is True but neither hip nor cuda version set; assuming CUDA.")
    return "cuda"


def get_device() -> str:
    """Return the torch device string for the current environment.

    Honors the `RADEON_STUDIO_DEVICE` env var (useful for tests / CPU dev),
    otherwise auto-detects. Always returns one of: "cuda", "cpu".
    """
    override = os.environ.get("RADEON_STUDIO_DEVICE", "").strip().lower()
    if override == "cpu":
        log.info("device override via env: cpu")
        return "cpu"
    if override in {"rocm", "cuda"}:
        log.info("device override via env: %s -> using 'cuda' (torch alias)", override)
        return "cuda"

    kind = detect_device_kind()
    if kind == "cpu":
        log.warning("No GPU detected — running on CPU (slow, dev only).")
        return "cpu"

    log.info("Active device: %s (%s)", kind, _torch_version_str())
    return "cuda"


def _torch_version_str() -> str:
    import torch
    if torch.version.hip:
        return f"ROCm {torch.version.hip}"
    if torch.version.cuda:
        return f"CUDA {torch.version.cuda}"
    return f"PyTorch {torch.__version__}"
