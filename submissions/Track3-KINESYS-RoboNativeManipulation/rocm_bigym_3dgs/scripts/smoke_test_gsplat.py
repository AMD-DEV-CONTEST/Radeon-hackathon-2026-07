#!/usr/bin/env python3
"""Compile/load gsplat on ROCm and render a finite one-Gaussian image."""

from __future__ import annotations

import torch
from gsplat import rasterization


def main() -> None:
    if torch.version.hip is None or not torch.cuda.is_available():
        raise SystemExit("ROCm PyTorch with a visible AMD GPU is required")
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
        raise SystemExit(f"invalid gsplat output: {tuple(image.shape)}")
    if not torch.isfinite(alpha).all() or float(alpha.max()) <= 0.0:
        raise SystemExit("invalid gsplat alpha output")
    print("GATE_OK", True)
    print("TORCH", torch.__version__, "HIP", torch.version.hip)
    print("DEVICE", torch.cuda.get_device_name(0))


if __name__ == "__main__":
    main()
