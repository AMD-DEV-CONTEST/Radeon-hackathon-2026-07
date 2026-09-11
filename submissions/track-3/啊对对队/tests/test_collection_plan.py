import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.collection_plan import (
    build_balanced_collection_plan,
    load_collection_requests,
)
from parcel_sorter.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CollectionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = PROJECT_ROOT / "configs" / "catalog_v1.toml"
        self.config = load_config(self.config_path)
        self.training_ids = [
            profile.profile_id
            for profile in self.config.parcel_profiles
            if not profile.evaluation_only
        ]

    def _audit_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for profile_id in self.training_ids:
            successes = 9 if profile_id == "micro_box" else 1
            for attempt in range(10):
                records.append(
                    {
                        "episode_index": len(records),
                        "success": attempt < successes,
                        "sample": {"profile_id": profile_id},
                    }
                )
        return records

    def test_plan_uses_history_for_effort_but_not_new_dataset_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "episodes.jsonl"
            audit_path.write_text(
                "".join(json.dumps(record) + "\n" for record in self._audit_records()),
                encoding="utf-8",
            )
            plan = build_balanced_collection_plan(
                profiles=self.config.parcel_profiles,
                audit_manifest=audit_path,
                config_path=self.config_path,
                target_successes_per_profile=5,
                planning_rate_floor=0.20,
                oversampling_factor=1.20,
                readiness_success_rate_lower_bound=0.30,
                start_episode=40,
            )

            entries = {entry["profile_id"]: entry for entry in plan["entries"]}
            self.assertEqual(plan["summary"]["target_successes_in_new_dataset"], 5 * len(self.training_ids))
            self.assertEqual(entries["micro_box"]["history"]["successes"], 9)
            self.assertEqual(entries["micro_box"]["target_successes_in_new_dataset"], 5)
            self.assertEqual(entries["micro_box"]["start_episode"], 40)
            self.assertEqual(entries["micro_box"]["status"], "ready")
            self.assertEqual(entries["mailing_tube"]["status"], "requires_expert_diagnostic")
            self.assertGreater(entries["mailing_tube"]["requested_episodes"], 5)
            self.assertIn("mailing_tube", plan["summary"]["blocked_profiles"])

    def test_loader_requires_explicit_acknowledgement_for_unready_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "entries": [
                            {
                                "profile_id": "micro_box",
                                "requested_episodes": 2,
                                "start_episode": 4,
                                "status": "ready",
                            },
                            {
                                "profile_id": "mailing_tube",
                                "requested_episodes": 3,
                                "start_episode": 8,
                                "status": "requires_expert_diagnostic",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "require expert diagnostics"):
                load_collection_requests(plan_path)
            requests = load_collection_requests(plan_path, allow_unready=True)
            self.assertEqual(
                [(request.profile_id, request.episodes, request.start_episode) for request in requests],
                [("micro_box", 2, 4), ("mailing_tube", 3, 8)],
            )

    def test_loader_rejects_config_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "episodes.jsonl"
            audit_path.write_text(
                "".join(json.dumps(record) + "\n" for record in self._audit_records()),
                encoding="utf-8",
            )
            plan = build_balanced_collection_plan(
                profiles=self.config.parcel_profiles,
                audit_manifest=audit_path,
                config_path=self.config_path,
                target_successes_per_profile=5,
            )
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "training catalog"):
                load_collection_requests(
                    plan_path,
                    expected_training_profile_ids=("micro_box",),
                )
            with self.assertRaisesRegex(ValueError, "configuration fingerprint"):
                load_collection_requests(
                    plan_path,
                    expected_config_path=audit_path,
                )
