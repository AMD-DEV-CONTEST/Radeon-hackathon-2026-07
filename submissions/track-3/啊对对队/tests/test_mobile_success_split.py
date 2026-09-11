import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.mobile_success_split import build_mobile_success_split


def _result(mode: str, cell_index: int, index: int) -> dict:
    episode_id = f"parcel-success-bulk-v6-{mode}-{index:04d}"
    return {
        "episode_id": episode_id,
        "parameters": {
            "episode_id": episode_id,
            "grasp_mode": mode,
            "design_cell": f"{mode}-cell-{cell_index:02d}",
            "source_identity": f"bulk/{mode}/{index:04d}",
            "demonstration_provenance": "deterministic_expert_candidate",
            "split": "collection_candidate",
        },
        "return_code": 0,
        "success": True,
        "failure_stage": None,
        "dataset_saved": True,
        "dataset_storage_format": "video",
        "dataset_bytes": 8_000_000,
        "frames": 594,
        "recovery_label": {"verified_success": True},
        "lift_success": True,
        "transport_success": True,
        "placed_before_release": True,
        "released": True,
        "place_force_safety_abort": False,
        "max_suction_force_n": 4.0,
        "max_contact_force_n": 20.0,
        "max_cradle_contact_force_n": 30.0 if mode == "cooperative_cradle" else None,
    }


class MobileSuccessSplitTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        results = []
        for mode in ("top_suction", "side_suction", "cooperative_cradle"):
            mode_index = 0
            for cell_index in range(8):
                count = 63 if cell_index < 4 else 62
                for _ in range(count):
                    results.append(_result(mode, cell_index, mode_index))
                    mode_index += 1
        summary = {
            "collection_id": "parcel-success-bulk-v6",
            "runtime_contract": {"config_sha256": "abc"},
            "status": "passed",
            "success_quota": {"complete": True, "target_successes": 1500},
            "results": results,
            "successful_episode_order": [item["episode_id"] for item in results],
        }
        summary_path = root / "collection-summary.json"
        info_path = root / "lerobot_dataset" / "meta" / "info.json"
        info_path.parent.mkdir(parents=True)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        features = {
            name: {"dtype": "video"}
            for name in (
                "observation.images.overhead_rgb",
                "observation.images.overhead_depth",
                "observation.images.overhead_depth_rgb",
                "observation.images.left_wrist_rgb",
                "observation.images.left_wrist_depth",
                "observation.images.left_wrist_depth_rgb",
            )
        }
        info_path.write_text(
            json.dumps(
                {
                    "total_episodes": 1500,
                    "video_path": (
                        "videos/{video_key}/chunk-{chunk_index:03d}/"
                        "file-{file_index:03d}.mp4"
                    ),
                    "features": features,
                }
            ),
            encoding="utf-8",
        )
        return summary_path, info_path

    def test_exact_stratified_split_is_deterministic_and_leak_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary, info = self._fixture(root)
            first = build_mobile_success_split(
                collection_summary=summary,
                dataset_info=info,
                output=root / "split-a.json",
            )
            second = build_mobile_success_split(
                collection_summary=summary,
                dataset_info=info,
                output=root / "split-b.json",
            )

            self.assertEqual(first, second)
            self.assertEqual(
                first["counts"],
                {"total": 1500, "train": 1200, "development": 150, "confirmation": 150},
            )
            expected_mode_counts = {"train": 400, "development": 50, "confirmation": 50}
            self.assertTrue(
                all(
                    counts == expected_mode_counts
                    for counts in first["mode_counts"].values()
                )
            )
            self.assertEqual(len(first["design_cell_counts"]), 24)
            split_sets = [set(first["lerobot"][key]) for key in (
                "train_episodes", "development_episodes", "confirmation_episodes"
            )]
            self.assertFalse(split_sets[0] & split_sets[1])
            self.assertFalse(split_sets[0] & split_sets[2])
            self.assertFalse(split_sets[1] & split_sets[2])
            self.assertEqual(len(set.union(*split_sets)), 1500)

    def test_force_violation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path, info_path = self._fixture(root)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["results"][0]["max_contact_force_n"] = 35.0
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "max_contact_force_n"):
                build_mobile_success_split(
                    collection_summary=summary_path,
                    dataset_info=info_path,
                    output=root / "split.json",
                )

    def test_incomplete_quota_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path, info_path = self._fixture(root)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["success_quota"]["complete"] = False
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "quota is incomplete"):
                build_mobile_success_split(
                    collection_summary=summary_path,
                    dataset_info=info_path,
                    output=root / "split.json",
                )


if __name__ == "__main__":
    unittest.main()
