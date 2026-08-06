"""Canonical generic COCO RT-DETRv2 evaluation entry point."""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "ppe" / "evaluate_rtdetr_coco.py"),
    run_name="__main__",
)
