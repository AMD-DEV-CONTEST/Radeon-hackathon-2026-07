import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.mobile_stratified_sampler import (
    build_sampling_manifest_from_dataset,
)
from parcel_sorter.mobile_train_stats import (
    _balanced_normalization_indices,
    build_train_only_normalization_stats,
    load_train_only_normalization_stats,
)


class MobileTrainStatsTests(unittest.TestCase):
    def _manifest(self) -> dict:
        pools = {}
        index = 0
        for mode in ("top_suction", "side_suction", "cooperative_cradle"):
            for cell in range(8):
                name = f"{mode}-cell-{cell:02d}"
                width = 4 + (cell % 2)
                pools[name] = list(range(index, index + width))
                index += width
        return {
            "seed": 20260729,
            "samples_per_design_cell_per_epoch": 4,
            "samples_per_epoch": 96,
            "indices_by_design_cell": pools,
        }

    def test_balanced_normalization_indices_are_unique_and_deterministic(self) -> None:
        manifest = self._manifest()
        first = _balanced_normalization_indices(manifest)
        second = _balanced_normalization_indices(manifest)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 96)
        self.assertEqual(len(set(first)), 96)

    def test_short_design_cell_fails_closed(self) -> None:
        manifest = self._manifest()
        manifest["indices_by_design_cell"]["top_suction-cell-00"] = [0, 1, 2]
        with self.assertRaisesRegex(ValueError, "too small"):
            _balanced_normalization_indices(manifest)

    def test_real_parquet_excludes_extreme_held_out_frames(self) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow is required for the real-Parquet integration test")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dataset"
            (root / "meta").mkdir(parents=True)
            (root / "data" / "chunk-000").mkdir(parents=True)
            info_path = root / "meta" / "info.json"
            info_path.write_text(
                json.dumps(
                    {
                        "fps": 30,
                        "total_episodes": 1500,
                        "total_frames": 9000,
                        "features": {
                            "observation.state": {
                                "dtype": "float32",
                                "shape": [2],
                                "names": ["state_0", "state_1"],
                            },
                            "action": {
                                "dtype": "float32",
                                "shape": [1],
                                "names": ["action_0"],
                            },
                            "observation.stage_id": {
                                "dtype": "int64",
                                "shape": [1],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "meta" / "stats.json").write_text(
                json.dumps(
                    {
                        "observation.state": {"mean": [0, 0], "std": [1, 1]},
                        "action": {"mean": [0], "std": [1]},
                    }
                ),
                encoding="utf-8",
            )
            assignments = []
            episode_index = 0
            modes = ("top_suction", "side_suction", "cooperative_cradle")
            for mode in modes:
                for cell in range(8):
                    for _ in range(50):
                        assignments.append(
                            {
                                "dataset_episode_index": episode_index,
                                "grasp_mode": mode,
                                "design_cell": f"{mode}-cell-{cell:02d}",
                                "split": "train",
                            }
                        )
                        episode_index += 1
            for split_name in ("development", "confirmation"):
                for held_out_index in range(150):
                    mode = modes[held_out_index % 3]
                    assignments.append(
                        {
                            "dataset_episode_index": episode_index,
                            "grasp_mode": mode,
                            "design_cell": (
                                f"{mode}-cell-{held_out_index % 8:02d}"
                            ),
                            "split": split_name,
                        }
                    )
                    episode_index += 1
            info_sha256 = hashlib.sha256(info_path.read_bytes()).hexdigest()
            split = {
                "counts": {
                    "total": 1500,
                    "train": 1200,
                    "development": 150,
                    "confirmation": 150,
                },
                "source": {"dataset_info_sha256": info_sha256},
                "assignments": assignments,
            }
            split_path = root / "PARCEL_SUCCESS_SPLIT.json"
            split_path.write_text(json.dumps(split), encoding="utf-8")

            indices = []
            episodes = []
            stages = []
            states = []
            actions = []
            frame_index = 0
            for episode in range(1500):
                held_out = episode >= 1200
                for stage in range(6):
                    value = 1_000_000.0 if held_out else float(episode + stage)
                    indices.append(frame_index)
                    episodes.append(episode)
                    stages.append(stage)
                    states.extend((value, value + 0.5))
                    actions.append(value)
                    frame_index += 1
            table = pa.table(
                {
                    "index": pa.array(indices, type=pa.int64()),
                    "episode_index": pa.array(episodes, type=pa.int64()),
                    "observation.stage_id": pa.array(stages, type=pa.int64()),
                    "observation.state": pa.FixedSizeListArray.from_arrays(
                        pa.array(states, type=pa.float32()), 2
                    ),
                    "action": pa.FixedSizeListArray.from_arrays(
                        pa.array(actions, type=pa.float32()), 1
                    ),
                }
            )
            pq.write_table(table, root / "data" / "chunk-000" / "file-000.parquet")
            sampling_path = root / "PARCEL_PI05_SAMPLING_MANIFEST.json"
            sampling = build_sampling_manifest_from_dataset(
                dataset_root=root,
                split_manifest_path=split_path,
                output=sampling_path,
                stage_frame_cap_per_episode=100,
            )
            train_stats_path = root / "meta" / "train_stats.json"
            train_stats_manifest = root / "PARCEL_TRAIN_STATS_MANIFEST.json"
            payload = build_train_only_normalization_stats(
                dataset_root=root,
                split_manifest_path=split_path,
                sampling_manifest_path=sampling_path,
                output_stats=train_stats_path,
                output_manifest=train_stats_manifest,
            )
            stats = load_train_only_normalization_stats(
                stats_path=train_stats_path,
                manifest_path=train_stats_manifest,
                sampling_manifest_path=sampling_path,
            )
            self.assertEqual(payload["normalization_frame_count"], 7200)
            self.assertEqual(
                payload["normalization_frame_count"], sampling["samples_per_epoch"]
            )
            self.assertEqual(payload["held_out_frame_count"], 0)
            self.assertLess(float(stats["action"]["max"][0]), 1_000_000.0)
