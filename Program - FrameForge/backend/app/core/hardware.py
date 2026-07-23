"""
Hardware profiling.

This module previously detected local GPU/CUDA/ROCm hardware for ComfyUI
workflow optimization. Since FrameForge now drives a remote API (Replicate),
local GPU detection is no longer needed. This module is kept for any future
local inference path or informational display.
"""


def build_pipeline_config() -> dict:
    """
    Returns a static config describing the cloud execution environment.
    When driving Replicate, the actual GPU details are opaque — we just
    know the resolution limits of the model.
    """
    return {
        "backend": "replicate",
        "device_name": "Replicate (cloud)",
        "vram_gb": 0.0,
        "gfx_arch": None,
        "attention_backend": "unknown",
        "precision": "unknown",
        "max_short_side": 768,
        "offload_mode": "none",
        "tier_name": "Replicate (cloud)",
    }


def summary_line(config: dict) -> str:
    return f"{config['tier_name']} | {config['device_name']} | precision={config['precision']}"
