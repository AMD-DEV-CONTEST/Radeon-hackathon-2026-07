"""Dependency-light checks for nuScenes metadata pairing and LiDAR binning."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np


def load_builder():
    project_root = Path(__file__).parents[1]
    sys.path.insert(0, str(project_root))
    cv2_stub = types.ModuleType("cv2")
    cv2_stub.IMREAD_COLOR = 1
    cv2_stub.COLOR_BGR2RGB = 1
    cv2_stub.COLOR_RGB2BGR = 2
    cv2_stub.INTER_AREA = 3
    cv2_stub.FONT_HERSHEY_SIMPLEX = 0
    cv2_stub.LINE_AA = 0
    sys.modules.setdefault("cv2", cv2_stub)
    path = project_root / "scripts" / "build_nuscenes_degradation_dataset.py"
    spec = importlib.util.spec_from_file_location("chronosafe_nuscenes_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_checks() -> None:
    builder = load_builder()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        metadata = root / "v1.0-mini"
        metadata.mkdir()
        write_json(metadata / "sensor.json", [
            {"token": "camera_sensor", "channel": "CAM_FRONT"},
            {"token": "lidar_sensor", "channel": "LIDAR_TOP"},
        ])
        write_json(metadata / "calibrated_sensor.json", [
            {"token": "camera_calibration", "sensor_token": "camera_sensor"},
            {"token": "lidar_calibration", "sensor_token": "lidar_sensor"},
        ])
        write_json(metadata / "scene.json", [{"token": "scene_token", "name": "scene-test"}])
        write_json(metadata / "sample.json", [
            {"token": "sample_a", "scene_token": "scene_token"},
            {"token": "sample_b", "scene_token": "scene_token"},
        ])
        write_json(metadata / "ego_pose.json", [
            {"token": "pose_a", "translation": [0.0, 0.0, 0.0]},
            {"token": "pose_b", "translation": [1.0, 0.0, 0.0]},
        ])
        sample_data = []
        for suffix, sample, timestamp, pose in (
            ("a", "sample_a", 1_000_000, "pose_a"),
            ("b", "sample_b", 2_000_000, "pose_b"),
        ):
            sample_data.extend(
                [
                    {
                        "sample_token": sample,
                        "calibrated_sensor_token": "camera_calibration",
                        "ego_pose_token": pose,
                        "timestamp": timestamp,
                        "filename": f"samples/CAM_FRONT/{suffix}.jpg",
                        "is_key_frame": True,
                    },
                    {
                        "sample_token": sample,
                        "calibrated_sensor_token": "lidar_calibration",
                        "ego_pose_token": pose,
                        "timestamp": timestamp + 20_000,
                        "filename": f"samples/LIDAR_TOP/{suffix}.pcd.bin",
                        "is_key_frame": True,
                    },
                ]
            )
            for filename in (
                f"samples/CAM_FRONT/{suffix}.jpg",
                f"samples/LIDAR_TOP/{suffix}.pcd.bin",
            ):
                sensor_file = root / filename
                sensor_file.parent.mkdir(parents=True, exist_ok=True)
                sensor_file.touch()
        write_json(metadata / "sample_data.json", sample_data)

        scenes = builder.discover_pairs(root, "v1.0-mini", max_sync_gap_ms=50.0)
        assert len(scenes) == 1
        assert scenes[0][1] == "scene-test"
        assert len(scenes[0][2]) == 2
        speeds = builder.estimate_speeds(scenes[0][2])
        assert np.allclose(speeds, [3.6, 3.6])

        lidar_path = root / "points.bin"
        points = np.asarray(
            [[10.0, 0.0, 0.0, 0.5, 0.0], [20.0, 0.0, 0.0, 0.5, 0.0]],
            dtype=np.float32,
        )
        points.tofile(lidar_path)
        ranges = builder.read_lidar(lidar_path, bins=64, max_range_m=50.0)
        assert ranges.shape == (64,)
        assert np.isclose(ranges.min(), 0.2)
        assert np.all((0.0 <= ranges) & (ranges <= 1.0))

        extractor = builder.TimingAwareHealthFeatureExtractor()
        timing_features = extractor.extract(
            np.zeros((8, 8, 3), dtype=np.float32),
            np.ones(64, dtype=np.float32),
            20.0,
            camera_age_frames=3,
            lidar_age_frames=2,
        )
        assert timing_features.shape == (15,)
        assert np.allclose(timing_features[10:13], [0.6, 0.4, 0.2])

        frozen_fault = builder.FaultParameters(frozen=True)
        assert builder.observable_sensor_ages(frozen_fault, step=7) == (7, 0)
        delayed_fault = builder.FaultParameters(delay=3)
        assert builder.observable_sensor_ages(delayed_fault, step=7) == (3, 3)

        manifest = [
            {
                "scene_id": scene_id,
                "scene_name": f"scene-{scene_id:03d}",
                "scene_token": f"scene-token-{scene_id}",
                "log_token": f"log-{scene_id // 2}",
                "pairs": 40,
            }
            for scene_id in range(12)
        ]
        split = builder.build_grouped_scene_split(manifest, 0.5, 0.25, seed=2026)
        split_ids = split["splits"]
        assert set(split_ids["train"]) | set(split_ids["calibration"]) | set(split_ids["test"]) == set(range(12))
        assert not (set(split_ids["train"]) & set(split_ids["calibration"]))
        assert not (set(split_ids["train"]) & set(split_ids["test"]))
        assert not (set(split_ids["calibration"]) & set(split_ids["test"]))
        log_sets = [set(split["log_tokens"][name]) for name in ("train", "calibration", "test")]
        assert not (log_sets[0] & log_sets[1] or log_sets[0] & log_sets[2] or log_sets[1] & log_sets[2])


class NuScenesBuilderTest(unittest.TestCase):
    def test_metadata_pairing_lidar_binning_and_grouped_split(self) -> None:
        run_checks()


if __name__ == "__main__":
    unittest.main(verbosity=2)
