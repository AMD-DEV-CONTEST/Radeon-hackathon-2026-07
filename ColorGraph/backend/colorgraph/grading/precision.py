from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass

import torch


@dataclass(frozen=True, slots=True)
class RenderPrecisionBudget:
    name: str
    minimum_decode_bits: int
    compute_dtype: str
    minimum_output_bits: int
    mixed_precision_allowed: bool
    maximum_normalized_channel_error: float
    maximum_delta_e_2000: float
    maximum_timestamp_error_seconds: float


# Interactive previews are explicitly an 8-bit display aid. A two-code-value
# channel budget includes image extraction, optional mixed precision and JPEG/
# browser-proxy quantization; it is not a mastering acceptance threshold.
PREVIEW_PRECISION_BUDGET = RenderPrecisionBudget(
    name="colorgraph.precision/preview-v1",
    minimum_decode_bits=8,
    compute_dtype="fp16_or_fp32",
    minimum_output_bits=8,
    mixed_precision_allowed=True,
    maximum_normalized_channel_error=2 / 255,
    maximum_delta_e_2000=1.0,
    maximum_timestamp_error_seconds=1 / 30,
)


# Formal renders decode and hand off 16-bit RGB, execute grading in FP32, and
# target at least a 10-bit master. The channel threshold applies before lossy
# delivery encoding; timestamp verification is enforced after muxing.
MASTER_PRECISION_BUDGET = RenderPrecisionBudget(
    name="colorgraph.precision/master-v1",
    minimum_decode_bits=16,
    compute_dtype="fp32",
    minimum_output_bits=10,
    mixed_precision_allowed=False,
    maximum_normalized_channel_error=0.5 / 65535,
    maximum_delta_e_2000=0.01,
    maximum_timestamp_error_seconds=5e-4,
)


def fp32_grading_context(device: torch.device) -> AbstractContextManager[None]:
    """Disable accelerator autocast around color-sensitive grading operations."""

    return torch.amp.autocast(device_type=device.type, enabled=False)
