"""Canonical generic COCO RT-DETRv2 training entry point.

The implementation remains in the legacy PPE path for backwards compatibility,
but it now accepts VISION_* variables and infers an arbitrary COCO class map.
"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "ppe" / "train_rtdetr_full.py"),
    run_name="__main__",
)
