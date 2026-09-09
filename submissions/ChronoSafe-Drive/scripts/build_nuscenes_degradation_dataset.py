"""Build a real-world RGB/LiDAR degradation dataset from nuScenes.

The converter intentionally uses only the Python standard library, NumPy and
OpenCV. It does not install or import nuscenes-devkit, so the validated ROCm
environment remains untouched.
"""

from __future__ import annotations

import argparse
import bisect
import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from chronosafe.faults import FaultInjector
from chronosafe.features import (
    FEATURE_NAMES,
    TIMING_FEATURE_NAMES,
    HealthFeatureExtractor,
    TimingAwareHealthFeatureExtractor,
    fault_risk_target,
)


@dataclass(frozen=True)
class SensorPair:
    timestamp: int
    camera_path: Path
    lidar_path: Path
    translation: np.ndarray


@dataclass(frozen=True)
class FaultParameters:
    blur_sigma: float = 0.0
    frozen: bool = False
    dropout: float = 0.0
    delay: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/nuscenes"))
    parser.add_argument("--version", default="v1.0-mini")
    parser.add_argument(
        "--output", type=Path, default=Path("data/chronosafe_nuscenes_mini.npz")
    )
    parser.add_argument("--augmentations", type=int, default=3)
    parser.add_argument("--image-size", type=int, default=84)
    parser.add_argument("--lidar-bins", type=int, default=64)
    parser.add_argument("--max-range-m", type=float, default=50.0)
    parser.add_argument("--max-pairs-per-scene", type=int, default=0)
    parser.add_argument("--max-scenes", type=int, default=0)
    parser.add_argument("--max-sync-gap-ms", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--feature-mode", choices=("basic", "timing"), default="basic")
    parser.add_argument(
        "--keyframes-only",
        action="store_true",
        help="Use only nuScenes sample keyframes (required for keyframe-only archives).",
    )
    parser.add_argument(
        "--split-output",
        type=Path,
        default=None,
        help="Optional deterministic log-grouped train/calibration/test split manifest.",
    )
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--calibration-fraction", type=float, default=0.15)
    parser.add_argument("--split-seed", type=int, default=2026)
    parser.add_argument(
        "--preview-dir", type=Path, default=Path("results/nuscenes_degradation_previews")
    )
    return parser.parse_args()


def load_json(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"nuScenes metadata file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return payload


def sensor_channel_lookup(metadata: Path) -> dict[str, str]:
    sensors = {str(item["token"]): str(item["channel"]) for item in load_json(metadata / "sensor.json")}
    return {
        str(item["token"]): sensors[str(item["sensor_token"])]
        for item in load_json(metadata / "calibrated_sensor.json")
    }


def discover_pairs(
    root: Path,
    version: str,
    max_sync_gap_ms: float,
    keyframes_only: bool = False,
    require_files: bool = True,
) -> list[tuple[str, str, list[SensorPair], str]]:
    metadata = root / version
    scenes = load_json(metadata / "scene.json")
    samples = load_json(metadata / "sample.json")
    sample_data = load_json(metadata / "sample_data.json")
    ego_poses = {
        str(item["token"]): np.asarray(item["translation"], dtype=np.float64)
        for item in load_json(metadata / "ego_pose.json")
    }
    channels = sensor_channel_lookup(metadata)
    sample_to_scene = {str(item["token"]): str(item["scene_token"]) for item in samples}
    scene_names = {str(item["token"]): str(item["name"]) for item in scenes}
    scene_logs = {
        str(item["token"]): str(item.get("log_token", item["token"])) for item in scenes
    }

    by_scene: dict[str, dict[str, list[dict[str, object]]]] = {
        token: {"CAM_FRONT": [], "LIDAR_TOP": []} for token in scene_names
    }
    for item in sample_data:
        if keyframes_only and not bool(item.get("is_key_frame", False)):
            continue
        channel = channels.get(str(item["calibrated_sensor_token"]))
        if channel not in {"CAM_FRONT", "LIDAR_TOP"}:
            continue
        if require_files and not (root / str(item["filename"])).is_file():
            continue
        scene_token = sample_to_scene.get(str(item["sample_token"]))
        if scene_token in by_scene:
            by_scene[scene_token][channel].append(item)

    discovered: list[tuple[str, str, list[SensorPair], str]] = []
    max_gap_us = max_sync_gap_ms * 1000.0
    for scene_token, streams in by_scene.items():
        cameras = sorted(streams["CAM_FRONT"], key=lambda item: int(item["timestamp"]))
        lidars = sorted(streams["LIDAR_TOP"], key=lambda item: int(item["timestamp"]))
        if not cameras or not lidars:
            continue
        lidar_timestamps = [int(item["timestamp"]) for item in lidars]
        pairs: list[SensorPair] = []
        for camera in cameras:
            timestamp = int(camera["timestamp"])
            insertion = bisect.bisect_left(lidar_timestamps, timestamp)
            candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(lidars)]
            lidar_index = min(candidates, key=lambda index: abs(lidar_timestamps[index] - timestamp))
            lidar = lidars[lidar_index]
            if abs(int(lidar["timestamp"]) - timestamp) > max_gap_us:
                continue
            pairs.append(
                SensorPair(
                    timestamp=timestamp,
                    camera_path=root / str(camera["filename"]),
                    lidar_path=root / str(lidar["filename"]),
                    translation=ego_poses[str(camera["ego_pose_token"])],
                )
            )
        if pairs:
            discovered.append(
                (scene_token, scene_names[scene_token], pairs, scene_logs[scene_token])
            )
    return sorted(discovered, key=lambda value: value[1])


def build_grouped_scene_split(
    scene_manifest: list[dict[str, object]],
    train_fraction: float,
    calibration_fraction: float,
    seed: int,
) -> dict[str, object]:
    """Create a deterministic split with no nuScenes log crossing partitions."""

    test_fraction = 1.0 - train_fraction - calibration_fraction
    fractions = np.asarray(
        [train_fraction, calibration_fraction, test_fraction], dtype=np.float64
    )
    if np.any(fractions <= 0.0) or not np.isclose(float(fractions.sum()), 1.0):
        raise ValueError("train/calibration/test fractions must be positive and sum to one")
    if len(scene_manifest) < 3:
        raise ValueError("At least three scenes are required to create a split")

    grouped: dict[str, list[dict[str, object]]] = {}
    for scene in scene_manifest:
        grouped.setdefault(str(scene["log_token"]), []).append(scene)
    if len(grouped) < 3:
        raise ValueError("At least three independent logs are required to create a split")

    rng = np.random.default_rng(seed)
    logs = list(grouped)
    rng.shuffle(logs)
    # Stable sorting preserves the randomized order among equally sized logs.
    logs.sort(key=lambda token: len(grouped[token]), reverse=True)
    target_counts = fractions * len(scene_manifest)
    split_names = ("train", "calibration", "test")
    assignments: dict[str, list[str]] = {name: [] for name in split_names}
    counts = np.zeros(3, dtype=np.int64)
    for log_token in logs:
        relative_deficit = (target_counts - counts) / np.maximum(target_counts, 1.0)
        split_index = int(np.argmax(relative_deficit))
        assignments[split_names[split_index]].append(log_token)
        counts[split_index] += len(grouped[log_token])

    splits: dict[str, list[int]] = {}
    split_logs: dict[str, list[str]] = {}
    for name in split_names:
        log_tokens = sorted(assignments[name])
        split_logs[name] = log_tokens
        splits[name] = sorted(
            int(scene["scene_id"])
            for token in log_tokens
            for scene in grouped[token]
        )
    return {
        "protocol": "deterministic nuScenes log-grouped scene split",
        "seed": seed,
        "requested_fractions": {
            "train": train_fraction,
            "calibration": calibration_fraction,
            "test": test_fraction,
        },
        "scene_count": len(scene_manifest),
        "log_count": len(grouped),
        "splits": splits,
        "log_tokens": split_logs,
        "actual_scene_counts": {name: len(splits[name]) for name in split_names},
    }


def observable_sensor_ages(fault: FaultParameters, step: int) -> tuple[int, int]:
    """Return causal packet ages exposed to the timing-aware feature extractor."""

    camera_age = max(fault.delay, step if fault.frozen else 0)
    return camera_age, fault.delay


def read_camera(path: Path, image_size: int) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read camera image: {path}")
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = cv2.resize(image, (image_size, image_size), interpolation=cv2.INTER_AREA)
    return image.astype(np.float32) / 255.0


def read_lidar(path: Path, bins: int, max_range_m: float) -> np.ndarray:
    raw = np.fromfile(path, dtype=np.float32)
    if raw.size == 0 or raw.size % 5:
        raise ValueError(f"Invalid nuScenes LiDAR point cloud: {path}")
    points = raw.reshape(-1, 5)[:, :3]
    distances = np.linalg.norm(points[:, :2], axis=1)
    valid = np.isfinite(points).all(axis=1) & (distances >= 0.5) & (distances <= max_range_m)
    points, distances = points[valid], distances[valid]
    ranges = np.ones(bins, dtype=np.float32)
    if len(points):
        angles = np.arctan2(points[:, 1], points[:, 0])
        indices = np.floor((angles + np.pi) * bins / (2.0 * np.pi)).astype(np.int64)
        indices = np.clip(indices, 0, bins - 1)
        np.minimum.at(ranges, indices, (distances / max_range_m).astype(np.float32))
    return ranges


def estimate_speeds(pairs: list[SensorPair]) -> np.ndarray:
    timestamps = np.asarray([pair.timestamp for pair in pairs], dtype=np.float64) / 1_000_000.0
    translations = np.stack([pair.translation for pair in pairs])
    speeds = np.zeros(len(pairs), dtype=np.float32)
    if len(pairs) > 1:
        elapsed = np.diff(timestamps)
        travelled = np.linalg.norm(np.diff(translations, axis=0), axis=1)
        valid = elapsed > 1e-4
        speeds[1:][valid] = (travelled[valid] / elapsed[valid] * 3.6).astype(np.float32)
        speeds[0] = speeds[1]
    return np.clip(speeds, 0.0, 160.0)


def base_sensor_augmentation(
    rgb: np.ndarray,
    lidar: np.ndarray,
    brightness: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    rgb_noise = rng.normal(0.0, 0.003, size=rgb.shape).astype(np.float32)
    lidar_noise = rng.normal(0.0, 0.0015, size=lidar.shape).astype(np.float32)
    return (
        np.clip(rgb * brightness + rgb_noise, 0.0, 1.0),
        np.clip(lidar + lidar_noise, 0.0, 1.0),
    )


def fault_parameters(
    scenario: str,
    progress: float,
    severity_scale: float,
    max_delay: int,
) -> FaultParameters:
    blur = np.clip((0.5 + 3.5 * progress) * severity_scale, 0.0, 4.0)
    dropout = np.clip((0.2 + 0.7 * progress) * severity_scale, 0.0, 0.95)
    delay = min(max_delay, 1 + int(progress * max_delay * severity_scale))
    if scenario == "progressive_blur":
        return FaultParameters(blur_sigma=float(blur))
    if scenario == "camera_freeze":
        return FaultParameters(frozen=True)
    if scenario == "lidar_dropout":
        return FaultParameters(dropout=float(dropout))
    if scenario == "dynamic_delay":
        return FaultParameters(delay=delay)
    if scenario == "freeze_plus_dropout":
        return FaultParameters(frozen=True, dropout=float(dropout))
    if scenario == "blur_plus_delay":
        return FaultParameters(blur_sigma=float(blur), delay=delay)
    return FaultParameters()


def corrupt_track(
    rgb_frames: list[np.ndarray],
    lidar_frames: list[np.ndarray],
    scenario: str,
    rng: np.random.Generator,
    max_delay: int = 5,
) -> tuple[list[np.ndarray], list[np.ndarray], list[FaultParameters]]:
    brightness = float(rng.uniform(0.88, 1.12))
    severity_scale = float(rng.uniform(0.82, 1.18))
    base_rgb, base_lidar = [], []
    for rgb, lidar in zip(rgb_frames, lidar_frames, strict=True):
        augmented_rgb, augmented_lidar = base_sensor_augmentation(rgb, lidar, brightness, rng)
        base_rgb.append(augmented_rgb)
        base_lidar.append(augmented_lidar)

    output_rgb, output_lidar, parameters = [], [], []
    frozen_rgb = base_rgb[0].copy()
    denominator = max(len(base_rgb) - 1, 1)
    for index in range(len(base_rgb)):
        progress = index / denominator
        fault = fault_parameters(scenario, progress, severity_scale, max_delay)
        source_index = max(0, index - fault.delay)
        rgb = base_rgb[source_index].copy()
        lidar = base_lidar[source_index].copy()
        if fault.frozen:
            rgb = frozen_rgb.copy()
        if fault.blur_sigma > 0.0:
            kernel = max(3, int(round(fault.blur_sigma * 4.0)) | 1)
            rgb = cv2.GaussianBlur(rgb, (kernel, kernel), sigmaX=fault.blur_sigma)
        if fault.dropout > 0.0:
            lidar[rng.random(lidar.shape) < fault.dropout] = 0.0
        output_rgb.append(rgb)
        output_lidar.append(lidar)
        parameters.append(fault)
    return output_rgb, output_lidar, parameters


def write_preview(path: Path, rgb: np.ndarray, scenario: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas = cv2.resize((np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8), (504, 504))
    canvas = cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)
    cv2.rectangle(canvas, (0, 0), (504, 54), (15, 23, 42), thickness=-1)
    cv2.putText(
        canvas,
        scenario,
        (16, 37),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    if not cv2.imwrite(str(path), canvas):
        raise RuntimeError(f"Could not write preview: {path}")


def main() -> None:
    args = parse_args()
    if args.augmentations < 1:
        raise ValueError("--augmentations must be at least 1")
    started = time.perf_counter()
    scenes = discover_pairs(
        args.root,
        args.version,
        args.max_sync_gap_ms,
        keyframes_only=args.keyframes_only,
    )
    if args.max_scenes > 0:
        scenes = scenes[: args.max_scenes]
    if not scenes:
        raise RuntimeError("No complete nuScenes RGB/LiDAR scenes were discovered")
    print(f"discovered scenes: {len(scenes)}", flush=True)

    features: list[np.ndarray] = []
    labels: list[int] = []
    risks: list[float] = []
    scene_ids: list[int] = []
    track_ids: list[int] = []
    steps: list[int] = []
    camera_ages: list[int] = []
    lidar_ages: list[int] = []
    blur_sigmas: list[float] = []
    frozen_flags: list[bool] = []
    dropout_rates: list[float] = []
    delay_frames: list[int] = []
    track_id = 0
    scene_manifest: list[dict[str, object]] = []
    total_pairs = 0

    for scene_id, (scene_token, scene_name, pairs, log_token) in enumerate(scenes):
        if args.max_pairs_per_scene > 0 and len(pairs) > args.max_pairs_per_scene:
            selected = np.linspace(0, len(pairs) - 1, args.max_pairs_per_scene).round().astype(int)
            pairs = [pairs[index] for index in selected]
        if len(pairs) < 8:
            print(f"skip {scene_name}: only {len(pairs)} synchronized pairs", flush=True)
            continue
        print(f"scene {scene_id + 1}/{len(scenes)}: {scene_name}, pairs={len(pairs)}", flush=True)
        rgb_frames = [read_camera(pair.camera_path, args.image_size) for pair in pairs]
        lidar_frames = [read_lidar(pair.lidar_path, args.lidar_bins, args.max_range_m) for pair in pairs]
        speeds = estimate_speeds(pairs)
        total_pairs += len(pairs)
        scene_manifest.append(
            {
                "scene_id": scene_id,
                "scene_name": scene_name,
                "scene_token": scene_token,
                "log_token": log_token,
                "pairs": len(pairs),
            }
        )

        for augmentation in range(args.augmentations):
            for scenario_index, scenario in enumerate(FaultInjector.SCENARIOS):
                rng = np.random.default_rng(args.seed + scene_id * 10007 + augmentation * 101 + scenario_index)
                faulty_rgb, faulty_lidar, fault_values = corrupt_track(
                    rgb_frames, lidar_frames, scenario, rng
                )
                extractor = (
                    TimingAwareHealthFeatureExtractor()
                    if args.feature_mode == "timing"
                    else HealthFeatureExtractor()
                )
                for step, (rgb, lidar, speed, fault) in enumerate(
                    zip(faulty_rgb, faulty_lidar, speeds, fault_values, strict=True)
                ):
                    camera_age, lidar_age = observable_sensor_ages(fault, step)
                    if isinstance(extractor, TimingAwareHealthFeatureExtractor):
                        feature = extractor.extract(
                            rgb,
                            lidar,
                            float(speed),
                            camera_age_frames=camera_age,
                            lidar_age_frames=lidar_age,
                        )
                    else:
                        feature = extractor.extract(rgb, lidar, float(speed))
                    features.append(feature)
                    labels.append(scenario_index)
                    risks.append(
                        fault_risk_target(
                            fault.blur_sigma,
                            fault.frozen,
                            fault.dropout,
                            fault.delay,
                        )
                    )
                    scene_ids.append(scene_id)
                    track_ids.append(track_id)
                    steps.append(step)
                    camera_ages.append(camera_age)
                    lidar_ages.append(lidar_age)
                    blur_sigmas.append(fault.blur_sigma)
                    frozen_flags.append(fault.frozen)
                    dropout_rates.append(fault.dropout)
                    delay_frames.append(fault.delay)
                if scene_id == 0 and augmentation == 0:
                    preview_index = min(len(faulty_rgb) - 1, max(7, len(faulty_rgb) * 3 // 4))
                    write_preview(
                        args.preview_dir / f"{scenario_index:02d}_{scenario}.jpg",
                        faulty_rgb[preview_index],
                        scenario,
                    )
                track_id += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        features=np.stack(features).astype(np.float32),
        labels=np.asarray(labels, dtype=np.int64),
        risks=np.asarray(risks, dtype=np.float32),
        scene_ids=np.asarray(scene_ids, dtype=np.int64),
        track_ids=np.asarray(track_ids, dtype=np.int64),
        steps=np.asarray(steps, dtype=np.int64),
        camera_age_frames=np.asarray(camera_ages, dtype=np.int16),
        lidar_age_frames=np.asarray(lidar_ages, dtype=np.int16),
        blur_sigma=np.asarray(blur_sigmas, dtype=np.float32),
        frozen=np.asarray(frozen_flags, dtype=np.bool_),
        dropout_rate=np.asarray(dropout_rates, dtype=np.float32),
        delay_frames=np.asarray(delay_frames, dtype=np.int16),
        feature_names=np.asarray(
            TIMING_FEATURE_NAMES if args.feature_mode == "timing" else FEATURE_NAMES
        ),
        class_names=np.asarray(FaultInjector.SCENARIOS),
    )
    elapsed = time.perf_counter() - started
    split_manifest = None
    if args.split_output is not None:
        split_manifest = build_grouped_scene_split(
            scene_manifest,
            args.train_fraction,
            args.calibration_fraction,
            args.split_seed,
        )
        args.split_output.parent.mkdir(parents=True, exist_ok=True)
        args.split_output.write_text(json.dumps(split_manifest, indent=2), encoding="utf-8")

    metadata = {
        "dataset": f"nuScenes {args.version}",
        "source": "https://www.nuscenes.org/",
        "license_note": "Use and redistribution remain subject to the current official nuScenes terms.",
        "modalities": ["CAM_FRONT", "LIDAR_TOP", "ego_pose"],
        "scenes": scene_manifest,
        "scene_count": len(scene_manifest),
        "synchronized_real_pairs": total_pairs,
        "augmentations_per_scenario": args.augmentations,
        "degradation_scenarios": list(FaultInjector.SCENARIOS),
        "samples": len(labels),
        "tracks": track_id,
        "features": list(TIMING_FEATURE_NAMES if args.feature_mode == "timing" else FEATURE_NAMES),
        "feature_mode": args.feature_mode,
        "keyframes_only": args.keyframes_only,
        "elapsed_seconds": round(elapsed, 3),
        "samples_per_second": round(len(labels) / elapsed, 3),
        "split_policy": "log-grouped split; no adjacent scenes from one nuScenes log cross partitions",
        "split_manifest": str(args.split_output) if args.split_output is not None else None,
        "raw_data_redistributed": False,
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in metadata.items() if key != "scenes"}, indent=2))
    print(f"dataset: {args.output}")
    if split_manifest is not None:
        print(f"split manifest: {args.split_output}")
        print(f"split scene counts: {split_manifest['actual_scene_counts']}")
    print(f"previews: {args.preview_dir}")
    print("ChronoSafe nuScenes degradation dataset: PASS")


if __name__ == "__main__":
    main()
