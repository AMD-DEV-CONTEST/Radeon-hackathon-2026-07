#!/usr/bin/env python3
"""Validate the AMD ROCm runtime before training or evaluation."""

from __future__ import annotations

import argparse
import importlib
import os
import platform


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-training", action="store_true")
    parser.add_argument("--require-3dgs", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ.setdefault("PYTORCH_ROCM_ARCH", "gfx1100")
    os.environ.setdefault("MAX_JOBS", "4")
    torch = importlib.import_module("torch")
    if torch.version.hip is None:
        raise RuntimeError("PyTorch is not a ROCm build")
    if not torch.cuda.is_available():
        raise RuntimeError("ROCm accelerator is not available")
    properties = torch.cuda.get_device_properties(0)
    architecture = getattr(properties, "gcnArchName", "")
    if "gfx1100" not in architecture:
        raise RuntimeError(f"Expected gfx1100, got {architecture!r}")

    required = ["transformers", "peft", "bigym", "mujoco"]
    if args.require_training:
        required.append("lerobot")
    if args.require_3dgs:
        required.extend(["gsplat", "gaussian_renderer", "plyfile"])
    for module in required:
        importlib.import_module(module)

    if args.require_3dgs:
        from gsplat import rasterization

        device = torch.device("cuda")
        means = torch.tensor([[0.0, 0.0, 2.0]], device=device)
        quats = torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device)
        scales = torch.tensor([[0.08, 0.08, 0.08]], device=device)
        opacities = torch.tensor([0.95], device=device)
        colors = torch.tensor([[1.0, 0.2, 0.1]], device=device)
        viewmats = torch.eye(4, device=device)[None]
        intrinsics = torch.tensor(
            [[[60.0, 0.0, 32.0], [0.0, 60.0, 32.0], [0.0, 0.0, 1.0]]],
            device=device,
        )
        image, alpha, _meta = rasterization(
            means,
            quats,
            scales,
            opacities,
            colors,
            viewmats,
            intrinsics,
            width=64,
            height=64,
        )
        torch.cuda.synchronize()
        if image.shape != (1, 64, 64, 3) or not torch.isfinite(image).all():
            raise RuntimeError("gsplat produced an invalid image")
        if not torch.isfinite(alpha).all() or float(alpha.max()) <= 0.0:
            raise RuntimeError("gsplat produced invalid alpha")

    print(f"python={platform.python_version()}")
    print(f"torch={torch.__version__}")
    print(f"hip={torch.version.hip}")
    print(f"device={torch.cuda.get_device_name(0)}")
    print(f"architecture={architecture}")
    print("AMD_PREFLIGHT_OK")


if __name__ == "__main__":
    main()
