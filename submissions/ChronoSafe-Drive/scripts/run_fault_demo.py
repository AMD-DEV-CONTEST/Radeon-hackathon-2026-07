"""Run the first ChronoSafe-Drive RGB/LiDAR temporal-fault experiment."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from metadrive import MetaDriveEnv
from metadrive.component.sensors.rgb_camera import RGBCamera

from chronosafe.faults import FaultInjector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=210)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("results/smoke"))
    return parser.parse_args()


def create_env(seed: int) -> MetaDriveEnv:
    return MetaDriveEnv(
        {
            "use_render": False,
            "image_observation": True,
            "stack_size": 1,
            "sensors": {"rgb_camera": (RGBCamera, 160, 90)},
            "vehicle_config": {"image_source": "rgb_camera"},
            "num_scenarios": 1,
            "start_seed": seed,
            "map": "S",
            "traffic_density": 0.12,
            "horizon": 1000,
        }
    )


def read_lidar(env: MetaDriveEnv) -> np.ndarray:
    points, _ = env.agent.lidar.perceive(
        base_vehicle=env.agent,
        physics_world=env.engine.physics_world.dynamic_world,
        num_lasers=64,
        distance=50,
    )
    return np.asarray(points, dtype=np.float32)


def sharpness(rgb: np.ndarray) -> float:
    gray = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def save_preview(path: Path, rgb: np.ndarray) -> None:
    bgr = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    preview_dir = args.output / "previews"
    preview_dir.mkdir(exist_ok=True)

    injector = FaultInjector(args.steps, seed=args.seed)
    env = create_env(args.seed)
    rows: list[dict[str, object]] = []
    scenario_counts: dict[str, int] = {}
    start = time.perf_counter()

    try:
        obs, _ = env.reset()
        last_scenario = ""

        for step in range(args.steps):
            raw_rgb = np.asarray(obs["image"], dtype=np.float32)[..., 0]
            raw_lidar = read_lidar(env)
            faulty_rgb, faulty_lidar, fault = injector.apply(step, raw_rgb, raw_lidar)

            if fault.name != last_scenario:
                save_preview(preview_dir / f"{step:04d}_{fault.name}.png", faulty_rgb)
                print(f"step={step:04d} scenario={fault.name}")
                last_scenario = fault.name

            scenario_counts[fault.name] = scenario_counts.get(fault.name, 0) + 1
            rows.append(
                {
                    "step": step,
                    "scenario": fault.name,
                    "blur_sigma": round(fault.blur_sigma, 4),
                    "camera_frozen": int(fault.camera_frozen),
                    "lidar_dropout_target": round(fault.lidar_dropout, 4),
                    "delay_frames": fault.delay_frames,
                    "camera_sharpness": round(sharpness(faulty_rgb), 4),
                    "camera_delta": round(float(np.mean(np.abs(faulty_rgb - raw_rgb))), 6),
                    "lidar_mean": round(float(faulty_lidar.mean()), 6),
                    "lidar_zero_ratio": round(float(np.mean(faulty_lidar == 0)), 6),
                    "speed_km_h": round(float(env.agent.speed_km_h), 4),
                }
            )

            action = np.asarray([0.0, 0.28], dtype=np.float32)
            obs, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                obs, _ = env.reset()
    finally:
        env.close()

    elapsed = time.perf_counter() - start
    csv_path = args.output / "fault_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "project": "ChronoSafe-Drive",
        "steps": len(rows),
        "seed": args.seed,
        "elapsed_seconds": round(elapsed, 3),
        "steps_per_second": round(len(rows) / elapsed, 3),
        "scenarios": scenario_counts,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "rocm_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"metrics: {csv_path}")
    print(f"previews: {preview_dir}")
    print("ChronoSafe fault demo: PASS")


if __name__ == "__main__":
    main()
