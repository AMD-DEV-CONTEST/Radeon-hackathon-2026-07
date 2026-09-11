import hashlib
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.campaign import (
    aggregate_by_category,
    campaign_fingerprint,
    catalog_profile_metadata,
    load_campaign,
    validate_campaign,
)


ROOT = Path(__file__).resolve().parents[1]


class CampaignTests(unittest.TestCase):
    def test_checked_in_campaign_is_valid_and_fingerprint_is_stable(self) -> None:
        path = ROOT / "configs" / "campaign_v1.toml"
        payload = load_campaign(path)
        self.assertEqual(payload["platform"]["backend"], "rocm")
        self.assertEqual(len(payload["evaluation"]["episode_ids"]), 20)
        self.assertEqual(campaign_fingerprint(payload), campaign_fingerprint(payload))

    def test_rejects_changed_safety_limit_and_duplicate_episode(self) -> None:
        payload = load_campaign(ROOT / "configs" / "campaign_v1.toml")
        payload["task"]["max_contact_force_n"] = 36.0
        with self.assertRaisesRegex(ValueError, "exactly 35.0"):
            validate_campaign(payload)
        payload = load_campaign(ROOT / "configs" / "campaign_v1.toml")
        payload["evaluation"]["episode_ids"].append(payload["evaluation"]["episode_ids"][0])
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_campaign(payload)

    def test_aggregates_shape_and_handling_class(self) -> None:
        records = [
            {
                "sample": {"profile_id": "box-a", "shape": "box", "handling_class": "parallel_jaw"},
                "result": {"success": True, "dropped": False, "max_contact_force_n": 4.0},
            },
            {
                "sample": {"profile_id": "tube-a", "shape": "cylinder", "orientation_mode": "horizontal"},
                "result": {"success": False, "dropped": True, "max_contact_force_n": 40.0},
            },
        ]
        result = aggregate_by_category(
            records,
            {"tube-a": {"shape": "cylinder", "orientation_mode": "horizontal", "handling_class": "parallel_jaw"}},
        )
        self.assertEqual(result["groups"]["box|parallel_jaw"]["success_rate"], 1.0)
        self.assertEqual(result["groups"]["horizontal_cylinder|parallel_jaw"]["force_abort_rate"], 1.0)

    def test_catalog_hash_is_a_real_sha256(self) -> None:
        catalog = ROOT / "configs" / "catalog_v2.toml"
        expected = hashlib.sha256(catalog.read_bytes()).hexdigest()
        payload = load_campaign(ROOT / "configs" / "campaign_v1.toml")
        self.assertEqual(payload["dataset"]["catalog_sha256"], expected)

    def test_catalog_metadata_reads_all_profile_classes(self) -> None:
        metadata = catalog_profile_metadata(ROOT / "configs" / "catalog_v2.toml")
        self.assertEqual(len(metadata), 21)
        self.assertEqual(metadata["mailing_tube"]["handling_class"], "parallel_jaw")
        self.assertEqual(metadata["large_cylinder_boundary"]["handling_class"], "cradle_required")

    def test_geometry_screen_campaign_freezes_unseen_profile_pairs(self) -> None:
        payload = load_campaign(ROOT / "configs" / "campaign_geometry_screen_v1.toml")
        evaluation = payload["evaluation"]
        self.assertEqual(evaluation["split"], "heldout")
        self.assertEqual(len(evaluation["profile_ids"]), 12)
        self.assertEqual(len(evaluation["local_episode_ids"]), 5)
        self.assertEqual(len(evaluation["episode_ids"]), 60)
        self.assertEqual(len(payload["experiments"]), 3)

    def test_reset_fallback_validation_uses_new_namespace_and_two_groups(self) -> None:
        payload = load_campaign(
            ROOT / "configs" / "campaign_reset_fallback_gate_validation_v1.toml"
        )
        evaluation = payload["evaluation"]
        self.assertEqual(evaluation["split"], "validation")
        self.assertEqual(evaluation["local_episode_ids"], list(range(120000, 120005)))
        self.assertEqual(len(evaluation["episode_ids"]), 60)
        self.assertTrue(set(evaluation["episode_ids"]).isdisjoint(range(200000, 200040)))
        self.assertEqual(len(payload["experiments"]), 2)
        self.assertIn(
            "--grasp-planning-reset-fallback-gate",
            payload["experiments"][1]["cli_args"],
        )

    def test_structured_campaign_rejects_incomplete_cartesian_product(self) -> None:
        payload = load_campaign(ROOT / "configs" / "campaign_geometry_screen_v1.toml")
        payload["evaluation"]["episode_ids"].pop()
        with self.assertRaisesRegex(ValueError, "every profile/local episode pair"):
            validate_campaign(payload)


if __name__ == "__main__":
    unittest.main()
