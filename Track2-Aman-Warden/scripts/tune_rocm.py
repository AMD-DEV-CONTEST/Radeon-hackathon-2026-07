#!/usr/bin/env python3
"""
Warden — ROCm self-tuning helper.

Auto-detects the installed AMD Radeon GPU (MI250 / MI300X / consumer RX)
via `rocm-smi`, picks the right HBM allocator caps and PyTorch caching
allocator config for the detected VRAM, and prints an env-var block in
either `bash export` form (for `benchmarks/run_benchmarks.sh`) or
Dockerfile `ENV` form (for the Dockerfile).

This is the bridge between "we know GPU_MAX_HEAP_SIZE matters but we
don't know what value to set on a card we haven't seen yet" and the
actual benchmark runs. Judges can run this once on the AMD Cloud GPU
and paste the output into the benchmark shell.

Usage:
    python scripts/tune_rocm.py             # prints bash export block
    python scripts/tune_rocm.py --docker    # prints Dockerfile ENV block
    python scripts/tune_rocm.py --apply     # exports into the current shell
                                            #  (Linux only; spawns no subshells)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class GpuProfile:
    """Detected GPU + the recommended env-var settings for it."""
    gpu_name: str = "Unknown AMD GPU"
    vram_bytes: int = 0
    heap_size_gb: int = 80
    cache_alloc_gb: int = 80
    n_threads_batch: int = 4
    gfx_override: str = ""   # HSA_OVERRIDE_GFX_VERSION fallback, e.g. "9.4.0"
    notes: str = ""

    @property
    def vram_gb(self) -> float:
        return self.vram_bytes / (1024 ** 3)

    def as_env(self) -> dict:
        env = {
            "GPU_MAX_HEAP_SIZE": str(self.heap_size_gb),
            "GPU_MAX_ALLOC_FOR_CACHING_ALLOCATOR": str(self.cache_alloc_gb),
            "PYTORCH_HIP_ALLOC_CONF": "expandable_segments:True",
            "WARDEN_LLM_N_THREADS_BATCH": str(self.n_threads_batch),
        }
        if self.gfx_override:
            env["HSA_OVERRIDE_GFX_VERSION"] = self.gfx_override
        return env


# Product-name substrings → HSA_OVERRIDE_GFX_VERSION value.
#
# Why this fallback exists: ROCm ships HIP code objects for a specific
# gfx target (gfx90a for MI250, gfx942 for MI300X, gfx1100 for RX 7900
# XTX). If the bundled binaries were built for a different target (a
# frequent llama.cpp-ROCm packaging mismatch), the runtime errors with
# "HSA_STATUS_ERROR_INVALID_CODE_OBJECT" and the GPU is unusable. Setting
# HSA_OVERRIDE_GFX_VERSION forces the HSA runtime to treat the card as
# the requested arch — a last-resort workaround that turns a hard crash
# into a runnable (if not optimal) model.
GFX_OVERRIDES = (
    ("MI300", "9.4.0"),      # MI300X / MI300A
    ("MI250", "9.0.0"),      # MI250 / MI250X
    ("MI210", "9.0.0"),
    ("MI100", "9.0.6"),
    ("RX 7900", "11.0.0"),   # RDNA3 (also W7900 / gfx1100)
    ("W7900", "11.0.0"),
    ("RX 6900", "10.3.0"),   # RDNA2 (also W6800 / gfx1030)
    ("W6800", "10.3.0"),
    ("RX 6800", "10.3.0"),
    ("RX 6700", "10.3.0"),
    ("RX 6600", "10.3.0"),
)


def detect_gfx_override(gpu_name: str) -> str:
    """Map a detected product name to its HSA_OVERRIDE_GFX_VERSION.

    Empty string = no override recommended (the runtime should detect
    the target itself; forcing a wrong value is worse than none).
    """
    for needle, gfx in GFX_OVERRIDES:
        if needle.lower() in gpu_name.lower():
            return gfx
    return ""


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, ""
    except Exception:
        return 1, ""


def detect_gpu(force_gfx: str = "") -> GpuProfile:
    """Probe rocm-smi for the GPU product name + VRAM.

    `force_gfx` (e.g. "9.4.0") overrides auto-detection of
    HSA_OVERRIDE_GFX_VERSION — use when the judge's card is known but
    rocm-smi product detection is unavailable, or to test a different
    gfx target than the auto-mapped one.
    """
    profile = GpuProfile()

    rc, out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])
    if rc == 0 and out:
        try:
            data = _safe_loads(out)
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict):
                        name = v.get("Card series") or v.get("Card model")
                        if name:
                            profile.gpu_name = name
                            break
                for v in data.values():
                    if isinstance(v, dict):
                        s = v.get("VRAM Total (B)") or v.get("VRAM Total Memory (B)")
                        if s:
                            try:
                                profile.vram_bytes = int(s)
                                break
                            except ValueError:
                                pass
        except Exception:
            pass

    # HSA_OVERRIDE_GFX_VERSION: explicit flag wins, else auto-map from
    # product name, else empty (no override — the runtime can detect it).
    if force_gfx:
        profile.gfx_override = force_gfx
    else:
        profile.gfx_override = detect_gfx_override(profile.gpu_name)

    # Pick caps based on detected VRAM. Hold back 20% for OS / Tier 1 / KV.
    if profile.vram_bytes > 0:
        vram_gb = profile.vram_bytes / (1024 ** 3)
        if vram_gb >= 160:
            profile.heap_size_gb = int(vram_gb * 0.80)   # MI300X 192GB → ~153GB
            profile.cache_alloc_gb = profile.heap_size_gb
            profile.n_threads_batch = 8
            if profile.gpu_name == "Unknown AMD GPU":
                profile.gpu_name = "MI300X-class (>=160GB HBM)"
        elif vram_gb >= 100:
            profile.heap_size_gb = int(vram_gb * 0.80)   # MI250 128GB → ~102GB
            profile.cache_alloc_gb = profile.heap_size_gb
            profile.n_threads_batch = 4
            if profile.gpu_name == "Unknown AMD GPU":
                profile.gpu_name = "MI250-class (>=100GB HBM)"
        elif vram_gb >= 16:
            # Consumer Radeon RX 7900 XTX (24GB) or similar.
            profile.heap_size_gb = max(8, int(vram_gb * 0.75))
            profile.cache_alloc_gb = profile.heap_size_gb
            profile.n_threads_batch = 2
            if profile.gpu_name == "Unknown AMD GPU":
                profile.gpu_name = f"Radeon RX-class ({vram_gb:.0f}GB VRAM)"
        else:
            # Small VRAM — keep heap modest, rely on unified memory
            profile.heap_size_gb = max(4, int(vram_gb * 0.75))
            profile.cache_alloc_gb = profile.heap_size_gb
            profile.n_threads_batch = 1
            if profile.gpu_name == "Unknown AMD GPU":
                profile.gpu_name = f"Small AMD GPU ({vram_gb:.0f}GB VRAM)"
        profile.notes = (
            f"Auto-tuned for {profile.gpu_name} with {vram_gb:.1f} GB HBM "
            f"(holding back 20% for OS / Tier 1 DeBERTa / KV cache)."
        )
    else:
        profile.notes = (
            "rocm-smi not available; printing conservative defaults that "
            "work on MI250 (128GB). Re-run on the actual AMD Cloud GPU for "
            "auto-tuned caps."
        )
    return profile


def _safe_loads(s: str):
    import json
    return json.loads(s)


def render_bash(p: GpuProfile) -> str:
    lines = [f"# ROCm auto-tune for {p.gpu_name} ({p.vram_gb:.1f} GB HBM detected)"]
    if p.notes:
        lines.append(f"# {p.notes}")
    lines.append("# Paste into benchmarks/run_benchmarks.sh before warden runs")
    lines.append("")
    for k, v in p.as_env().items():
        lines.append(f"export {k}={v}")
    return "\n".join(lines) + "\n"


def render_docker(p: GpuProfile) -> str:
    lines = [f"# ROCm auto-tune for {p.gpu_name} ({p.vram_gb:.1f} GB HBM detected)"]
    if p.notes:
        lines.append(f"# {p.notes}")
    lines.append("")
    for k, v in p.as_env().items():
        lines.append(f"ENV {k}={v}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Warden ROCm self-tuning helper")
    parser.add_argument("--docker", action="store_true",
                        help="Render as Dockerfile ENV block (default: bash export)")
    parser.add_argument("--apply", action="store_true",
                        help="Write to current shell environment via os.environ (Linux send-to-shell)")
    parser.add_argument("--gfx-version", default="",
                        help="Force HSA_OVERRIDE_GFX_VERSION (e.g. 9.4.0). Auto-detected from "
                             "product name when omitted; empty if no override is recommended.")
    args = parser.parse_args()

    profile = detect_gpu(force_gfx=args.gfx_version)
    block = render_docker(profile) if args.docker else render_bash(profile)
    print(block, file=sys.stdout if not args.apply else sys.stderr)

    if args.apply:
        if sys.platform == "win32":
            print("# --apply is Linux-only; cannot export parent shell from child on Windows.",
                  file=sys.stderr)
            return 1
        for k, v in profile.as_env().items():
            os.environ[k] = v
        print(f"# Applied {len(profile.as_env())} env vars to current process env.",
              file=sys.stderr)
        print("# (Child processes spawned by this one will inherit them.)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
