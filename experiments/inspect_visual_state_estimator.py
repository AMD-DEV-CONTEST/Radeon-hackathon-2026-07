"""Audit visual HDF5 supervision and an optional visual-state checkpoint."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

from algorithms.vision_state_estimator import VisualTaskStateEstimator
from data import build_dataloader
from experiments.train_visual_state_estimator import _task_positions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    device = torch.device(args.device)
    loader = build_dataloader(
        args.dataset, batch_size=args.batch_size, shuffle=False, num_workers=0,
        modalities=("state", "proprio", "rgb"),
    )
    first = next(iter(loader))
    _, rgb = _task_positions(first["state"]), first["rgb"]
    position_min = torch.full((6,), float("inf"))
    position_max = torch.full((6,), float("-inf"))
    for batch in loader:
        labels = _task_positions(batch["state"])
        position_min = torch.minimum(position_min, labels.amin(0))
        position_max = torch.maximum(position_max, labels.amax(0))
    report: dict[str, object] = {
        "transitions": len(loader.dataset),
        "rgb_shape": list(rgb.shape[1:]),
        "rgb_min": int(rgb.min()),
        "rgb_max": int(rgb.max()),
        "rgb_std": float(rgb.float().std()),
        "first_batch_frame_l1_change": float(
            (rgb[1:].float() - rgb[:-1].float()).abs().mean()
        ) if len(rgb) > 1 else 0.0,
        "object_xyz_min": position_min[:3].tolist(),
        "object_xyz_max": position_max[:3].tolist(),
        "target_xyz_min": position_min[3:].tolist(),
        "target_xyz_max": position_max[3:].tolist(),
    }
    if args.checkpoint is not None:
        payload = torch.load(args.checkpoint, map_location=device, weights_only=False)
        model = VisualTaskStateEstimator(
            image_height=payload["image_height"], image_width=payload["image_width"],
            proprio_dim=payload["proprio_dim"],
        ).to(device).eval()
        model.load_state_dict(payload["state_dict"])
        mean = payload["position_mean"].to(device)
        std = payload["position_std"].to(device)
        squared_error_sum = torch.zeros(6, device=device)
        count = 0
        with torch.inference_mode():
            for batch in loader:
                prediction = model(batch["rgb"].to(device), batch["proprio"].to(device)) * std + mean
                labels = _task_positions(batch["state"].to(device))
                squared_error_sum += (prediction - labels).square().sum(0)
                count += labels.shape[0]
        rmse = (squared_error_sum / count).sqrt().cpu().numpy()
        report["checkpoint_train_object_position_rmse_m"] = float(np.linalg.norm(rmse[:3]))
        report["checkpoint_train_target_position_rmse_m"] = float(np.linalg.norm(rmse[3:]))
    print(report)


if __name__ == "__main__":
    main()
