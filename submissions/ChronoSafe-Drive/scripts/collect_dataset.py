"""Collect multi-seed causal health features from compound sensor faults."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from metadrive import MetaDriveEnv
from metadrive.component.sensors.rgb_camera import RGBCamera

from chronosafe.faults import FaultInjector
from chronosafe.features import (
    FEATURE_NAMES,
    TIMING_FEATURE_NAMES,
    HealthFeatureExtractor,
    TimingAwareHealthFeatureExtractor,
    fault_risk_target,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="7,11,19,23")
    parser.add_argument("--steps-per-seed", type=int, default=140)
    parser.add_argument("--output", type=Path, default=Path("data/chronosafe_dataset.npz"))
    parser.add_argument("--feature-mode", choices=("basic", "timing"), default="basic")
    return parser.parse_args()


def create_env(seed: int) -> MetaDriveEnv:
    return MetaDriveEnv(
        {
            "use_render": False,
            "image_observation": True,
            "stack_size": 1,
            "sensors": {"rgb_camera": (RGBCamera, 84, 84)},
            "vehicle_config": {"image_source": "rgb_camera"},
            "num_scenarios": 1,
            "start_seed": seed,
            "map": "S",
            "traffic_density": 0.15,
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


def main() -> None:
    args = parse_args()
    seeds = [int(item.strip()) for item in args.seeds.split(",") if item.strip()]
    if len(seeds) < 3:
        raise ValueError("Use at least three seeds for train/calibration/test splits")

    all_features: list[np.ndarray] = []
    all_labels: list[int] = []
    all_risks: list[float] = []
    all_seeds: list[int] = []
    all_steps: list[int] = []
    start = time.perf_counter()

    for seed_index, seed in enumerate(seeds, start=1):
        print(f"seed {seed_index}/{len(seeds)}: {seed}", flush=True)
        env = create_env(seed)
        injector = FaultInjector(args.steps_per_seed, seed=seed)
        extractor = (
            TimingAwareHealthFeatureExtractor()
            if args.feature_mode == "timing"
            else HealthFeatureExtractor()
        )
        control_rng = np.random.default_rng(seed + 10000)
        longitudinal_action = 0.28
        try:
            obs, _ = env.reset()
            for step in range(args.steps_per_seed):
                rgb = np.asarray(obs["image"], dtype=np.float32)[..., 0]
                lidar = read_lidar(env)
                faulty_rgb, faulty_lidar, fault = injector.apply(step, rgb, lidar)
                if isinstance(extractor, TimingAwareHealthFeatureExtractor):
                    feature = extractor.extract(
                        faulty_rgb,
                        faulty_lidar,
                        env.agent.speed_km_h,
                        camera_age_frames=fault.delay_frames,
                        lidar_age_frames=fault.delay_frames,
                    )
                else:
                    feature = extractor.extract(faulty_rgb, faulty_lidar, env.agent.speed_km_h)

                all_features.append(feature)
                all_labels.append(FaultInjector.SCENARIOS.index(fault.name))
                all_risks.append(
                    fault_risk_target(
                        fault.blur_sigma,
                        fault.camera_frozen,
                        fault.lidar_dropout,
                        fault.delay_frames,
                    )
                )
                all_seeds.append(seed)
                all_steps.append(step)

                if step % 12 == 0:
                    longitudinal_action = float(
                        control_rng.choice(np.asarray([-0.18, 0.05, 0.18, 0.30]))
                    )
                action = np.asarray([0.0, longitudinal_action], dtype=np.float32)
                obs, _, terminated, truncated, _ = env.step(action)
                if terminated or truncated:
                    obs, _ = env.reset()
                    extractor.reset()
        finally:
            env.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        features=np.stack(all_features).astype(np.float32),
        labels=np.asarray(all_labels, dtype=np.int64),
        risks=np.asarray(all_risks, dtype=np.float32),
        seeds=np.asarray(all_seeds, dtype=np.int64),
        steps=np.asarray(all_steps, dtype=np.int64),
        feature_names=np.asarray(
            TIMING_FEATURE_NAMES if args.feature_mode == "timing" else FEATURE_NAMES
        ),
        class_names=np.asarray(FaultInjector.SCENARIOS),
    )

    elapsed = time.perf_counter() - start
    metadata = {
        "seeds": seeds,
        "steps_per_seed": args.steps_per_seed,
        "samples": len(all_labels),
        "features": list(TIMING_FEATURE_NAMES if args.feature_mode == "timing" else FEATURE_NAMES),
        "classes": list(FaultInjector.SCENARIOS),
        "elapsed_seconds": round(elapsed, 3),
        "samples_per_second": round(len(all_labels) / elapsed, 3),
        "control_profile": "seeded_random_longitudinal_action",
        "feature_mode": args.feature_mode,
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    print(f"dataset: {args.output}")
    print("ChronoSafe dataset collection: PASS")


if __name__ == "__main__":
    main()
