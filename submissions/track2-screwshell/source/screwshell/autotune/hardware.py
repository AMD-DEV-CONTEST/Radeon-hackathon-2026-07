"""Hardware probing for ScrewShell autotune (L2 detection layer).

Detects the GPU via rocm-smi (AMD) or nvidia-smi (NVIDIA), parses total VRAM,
and derives a HardwareProfile: vendor, name, total VRAM, a usable budget, and a
recommended quantization + rough tok/s estimate for the target base model.

Stdlib-only on purpose (no torch/CUDA import) so it runs on the deploy host
over SSH where rocm-smi lives, and in unit tests with a mocked profile.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field

# Target base model and its VRAM-by-quantization (GB). Qwen3.6-27B, GGUF.
# Numbers are planning estimates; the real floor is measured by
# scripts/bench_restart_swap.py on the actual hardware.
BASE_MODEL = "Qwen/Qwen3.6-27B"
QUANT_VRAM_GB = {
    "Q2_K": 11.0, "Q3_K_M": 14.0, "Q3_K_L": 15.5,
    "Q4_K_S": 16.5, "Q4_K_M": 18.9, "Q5_K_M": 21.0,
    "Q6_K": 24.0, "Q8_0": 29.0,
}
# OS / KV-cache headroom we never count as usable for weights (GB)
_RESERVE_GB = 2.0
# rough decode tok/s for a 48GB-class AMD ROCm GPU at Q4_K_M (README: ~26)
_TOKS_Q4_REF = 26.0
# subjective quality of each quant (0..1), higher = better
_QUANT_QUALITY = {
    "Q2_K": 0.35, "Q3_K_M": 0.55, "Q3_K_L": 0.60,
    "Q4_K_S": 0.68, "Q4_K_M": 0.78, "Q5_K_M": 0.88,
    "Q6_K": 0.94, "Q8_0": 0.98,
}


@dataclass
class HardwareProfile:
    vendor: str            # "amd" | "nvidia" | "unknown"
    name: str
    vram_total_gb: float | None
    smi_tool: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def vram_usable_gb(self) -> float | None:
        if self.vram_total_gb is None:
            return None
        return max(0.0, self.vram_total_gb - _RESERVE_GB)

    @classmethod
    def unknown(cls) -> "HardwareProfile":
        return cls(vendor="unknown", name="unknown", vram_total_gb=None)

    def recommend_quant(self, base_vram_map: dict | None = None) -> str | None:
        """Pick the highest-quality quant whose base fits in usable VRAM."""
        vmap = base_vram_map or QUANT_VRAM_GB
        usable = self.vram_usable_gb
        if usable is None:
            return None
        best = None
        # sorted by quality ascending -> last fitting one wins (highest quality)
        for q, gb in sorted(vmap.items(), key=lambda kv: _QUANT_QUALITY.get(kv[0], 0)):
            if gb <= usable:
                best = q
        return best

    def estimate_toks(self, quant: str | None) -> float | None:
        if quant is None or self.vram_total_gb is None:
            return None
        q = _QUANT_QUALITY.get(quant, 0.78)
        # scale reference Q4 perf by quant quality (coarser => faster) and by
        # GPU size (smaller GPU => lower memory bandwidth)
        size_factor = min(1.0, self.vram_total_gb / 48.0) ** 0.25
        return round(_TOKS_Q4_REF * (0.6 + 0.4 * q) * size_factor, 1)

    def fit_score(self, required_gb: float) -> float:
        usable = self.vram_usable_gb
        if usable is None:
            return 0.0
        return 1.0 if required_gb <= usable else max(0.0, 1 - (required_gb - usable) / usable)


def _detect_rocm() -> HardwareProfile | None:
    if not shutil.which("rocm-smi"):
        return None
    try:
        name = subprocess.run(["rocm-smi", "-i"], capture_output=True,
                              text=True, timeout=10).stdout
        mem = subprocess.run(["rocm-smi", "--showmeminfo", "vram"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    m = re.search(r"Total Memory \(B\):\s*(\d+)", mem)
    if not m:
        return None
    total = int(m.group(1)) / 1e9
    nm = re.search(r"GPU\[\d+\]\s*:\s*(.+)", name)
    return HardwareProfile(
        vendor="amd",
        name=(nm.group(1).strip() if nm else "AMD GPU"),
        vram_total_gb=round(total, 1), smi_tool="rocm-smi",
        raw={"mem": mem[:200]},
    )


def _detect_nvidia() -> HardwareProfile | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    line = out.strip().splitlines()[0] if out.strip() else ""
    if not line:
        return None
    name, _, vram = line.partition(",")
    return HardwareProfile(
        vendor="nvidia", name=name.strip(),
        vram_total_gb=float(vram.strip()), smi_tool="nvidia-smi",
        raw={"query": out[:200]},
    )


def detect() -> HardwareProfile:
    """Probe the system; fall back to unknown if no GPU tool is available."""
    for fn in (_detect_rocm, _detect_nvidia):
        prof = fn()
        if prof:
            return prof
    return HardwareProfile.unknown()
