import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.dataset_split import (
    build_split_manifest,
    lerobot_episode_argument,
    lerobot_eval_split,
)


class DatasetSplitTests(unittest.TestCase):
    def test_split_is_deterministic_stratified_and_leak_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_root = root / "audit"
            dataset_root = root / "dataset"
            audit_root.mkdir()
            (dataset_root / "meta").mkdir(parents=True)
            records = []
            for index in range(20):
                profile = "box" if index < 10 else "tube"
                records.append(
                    {
                        "episode_index": 1000 + index,
                        "success": True,
                        "sample": {"profile_id": profile},
                    }
                )
            records.append(
                {
                    "episode_index": 9999,
                    "success": False,
                    "sample": {"profile_id": "box"},
                }
            )
            (audit_root / "episodes.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
            )
            (audit_root.parent / "summary.json").write_text(
                json.dumps({"episodes": records}) + "\n", encoding="utf-8"
            )
            (dataset_root / "meta" / "info.json").write_text(
                json.dumps({"total_episodes": 20, "total_tasks": 1}), encoding="utf-8"
            )
            first = build_split_manifest(
                audit_manifest=audit_root / "episodes.jsonl",
                dataset_info=dataset_root / "meta" / "info.json",
                collection_summary=audit_root.parent / "summary.json",
                output=root / "split-a.json",
                seed=7,
            )
            second = build_split_manifest(
                audit_manifest=audit_root / "episodes.jsonl",
                dataset_info=dataset_root / "meta" / "info.json",
                collection_summary=audit_root.parent / "summary.json",
                output=root / "split-b.json",
                seed=7,
            )

            self.assertEqual(first, second)
            self.assertEqual(first["counts"], {"total": 20, "train": 14, "validation": 2, "heldout": 4})
            assignments = first["assignments"]
            self.assertEqual({item["original_episode_index"] for item in assignments}, set(range(1000, 1020)))
            for profile in ("box", "tube"):
                profile_splits = [item["split"] for item in assignments if item["profile_id"] == profile]
                self.assertEqual({"train", "validation", "heldout"}, set(profile_splits))
            self.assertEqual(json.loads(lerobot_episode_argument(root / "split-a.json")), first["lerobot"]["episodes"])
            self.assertEqual(lerobot_eval_split(root / "split-a.json"), "0.125")

            invalid = json.loads((root / "split-a.json").read_text(encoding="utf-8"))
            invalid["lerobot"]["heldout_episodes"].append(invalid["lerobot"]["episodes"][0])
            (root / "split-invalid.json").write_text(
                json.dumps(invalid), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "held-out episodes leak"):
                lerobot_episode_argument(root / "split-invalid.json")

    def test_incomplete_collection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_root = root / "audit"
            dataset_root = root / "dataset"
            audit_root.mkdir()
            (dataset_root / "meta").mkdir(parents=True)
            (audit_root / "episodes.jsonl").write_text("", encoding="utf-8")
            (dataset_root / "meta" / "info.json").write_text(
                json.dumps({"total_episodes": 0}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "summary is missing"):
                build_split_manifest(
                    audit_manifest=audit_root / "episodes.jsonl",
                    dataset_info=dataset_root / "meta" / "info.json",
                    collection_summary=audit_root.parent / "summary.json",
                    output=root / "split.json",
                )

    def test_multitask_dataset_is_rejected_by_schema_v1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_root = root / "audit"
            dataset_root = root / "dataset"
            audit_root.mkdir()
            (dataset_root / "meta").mkdir(parents=True)
            record = {
                "episode_index": 1,
                "success": True,
                "sample": {"profile_id": "box"},
            }
            (audit_root / "episodes.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            (audit_root.parent / "summary.json").write_text(
                json.dumps({"episodes": [record]}) + "\n", encoding="utf-8"
            )
            (dataset_root / "meta" / "info.json").write_text(
                json.dumps({"total_episodes": 1, "total_tasks": 2}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "single-task"):
                build_split_manifest(
                    audit_manifest=audit_root / "episodes.jsonl",
                    dataset_info=dataset_root / "meta" / "info.json",
                    collection_summary=audit_root.parent / "summary.json",
                    output=root / "split.json",
                )


if __name__ == "__main__":
    unittest.main()
