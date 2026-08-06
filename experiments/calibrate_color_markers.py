"""Fit pixel-to-table homographies from marker-rendered HDF5 demonstrations."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from controller.color_marker_perception import ColorMarkerPerception, MarkerCalibration
from data import RobotInteractionDataset


def _fit(pixels: list[np.ndarray], world: list[np.ndarray]) -> tuple[np.ndarray, float]:
    homography, mask = cv2.findHomography(np.asarray(pixels), np.asarray(world), cv2.RANSAC, 0.01)
    if homography is None or mask is None or int(mask.sum()) < 4:
        raise RuntimeError("insufficient valid marker detections for homography calibration")
    projected = cv2.perspectiveTransform(np.asarray(pixels, dtype=np.float32).reshape(-1, 1, 2), homography).reshape(-1, 2)
    error = np.linalg.norm(projected - np.asarray(world), axis=1)
    return homography.astype(np.float32), float(np.mean(error[mask.reshape(-1).astype(bool)]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("datasets/expert_visual_stage34_marker"))
    parser.add_argument("--output", type=Path, default=Path("checkpoints/color_servo/calibration.json"))
    args = parser.parse_args()
    dataset = RobotInteractionDataset(args.dataset, modalities=("state", "rgb"))
    object_pixels: list[np.ndarray] = []
    object_world: list[np.ndarray] = []
    target_pixels: list[np.ndarray] = []
    target_world: list[np.ndarray] = []
    for index in range(len(dataset)):
        sample = dataset[index]
        state, rgb = sample["state"].numpy(), sample["rgb"].numpy()
        object_pixel = ColorMarkerPerception.red_centroid(rgb)
        target_pixel = ColorMarkerPerception.green_centroid(rgb)
        # Calibrate the red object only while it lies on the table.
        if object_pixel is not None and state[27] <= 0.06:
            object_pixels.append(object_pixel)
            object_world.append(state[25:27])
        if target_pixel is not None:
            target_pixels.append(target_pixel)
            target_world.append(state[32:34])
    object_h, object_error = _fit(object_pixels, object_world)
    target_h, target_error = _fit(target_pixels, target_world)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    MarkerCalibration(object_h, target_h).save(args.output, metadata={
        "dataset": str(args.dataset), "object_samples": len(object_pixels), "target_samples": len(target_pixels),
        "object_fit_mean_error_m": object_error, "target_fit_mean_error_m": target_error,
    })
    dataset.close()
    print({"calibration": str(args.output), "object_fit_mean_error_m": object_error, "target_fit_mean_error_m": target_error})


if __name__ == "__main__":
    main()
