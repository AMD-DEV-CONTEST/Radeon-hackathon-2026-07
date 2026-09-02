"""Per-stage wall-clock + peak-VRAM accounting, rendered as a markdown table
for the UI, the benchmark script, and the demo video.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import torch

from .device import reset_vram_peak, vram_peak_gb


@dataclass
class StageRecord:
    name: str
    seconds: float
    vram_peak_gb: float


@dataclass
class RunTimings:
    stages: list[StageRecord] = field(default_factory=list)

    @contextmanager
    def stage(self, name: str, device: torch.device):
        reset_vram_peak(device)
        t0 = time.perf_counter()
        try:
            yield
        finally:
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            self.stages.append(
                StageRecord(name, time.perf_counter() - t0, vram_peak_gb(device))
            )

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.stages)

    def as_dict(self) -> dict:
        return {
            "stages": [
                {"name": s.name, "seconds": round(s.seconds, 2), "vram_peak_gb": s.vram_peak_gb}
                for s in self.stages
            ],
            "total_seconds": round(self.total_seconds, 2),
        }

    def as_markdown(self) -> str:
        lines = ["| Stage | Time (s) | Peak VRAM (GB) |", "|---|---:|---:|"]
        for s in self.stages:
            lines.append(f"| {s.name} | {s.seconds:.2f} | {s.vram_peak_gb:.2f} |")
        lines.append(f"| **Total** | **{self.total_seconds:.2f}** | |")
        return "\n".join(lines)
