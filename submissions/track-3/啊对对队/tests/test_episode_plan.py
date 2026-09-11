from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.episode_plan import (
    CollectionRequest,
    build_episode_plan,
    build_profile_episode_plan,
    catalog_episode_index,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EpisodePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(PROJECT_ROOT / "configs" / "catalog_v1.toml")

    def test_unfiltered_plan_preserves_contiguous_episodes(self) -> None:
        plan = build_episode_plan(self.config.parcel_profiles, 3, 7)
        self.assertEqual([item.episode_index for item in plan], [7, 8, 9])
        self.assertTrue(all(item.profile_id is None for item in plan))

    def test_profile_plan_is_balanced_and_namespaced(self) -> None:
        plan = build_episode_plan(
            self.config.parcel_profiles,
            2,
            5,
            ("micro_box", "mailing_tube"),
            allow_evaluation_only=False,
        )
        self.assertEqual(
            [(item.profile_id, item.local_index) for item in plan],
            [
                ("micro_box", 5),
                ("micro_box", 6),
                ("mailing_tube", 5),
                ("mailing_tube", 6),
            ],
        )
        self.assertEqual(len({item.episode_index for item in plan}), 4)

    def test_duplicate_profile_selection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            build_episode_plan(
                self.config.parcel_profiles,
                1,
                0,
                ("micro_box", "micro_box"),
            )

    def test_evaluation_only_profile_is_not_collectable(self) -> None:
        with self.assertRaisesRegex(ValueError, "evaluation-only"):
            build_episode_plan(
                self.config.parcel_profiles,
                1,
                0,
                ("usps_medium_flat_rate",),
                allow_evaluation_only=False,
            )

    def test_profile_requests_support_different_collection_budgets(self) -> None:
        plan = build_profile_episode_plan(
            self.config.parcel_profiles,
            (
                CollectionRequest("micro_box", episodes=1, start_episode=5),
                CollectionRequest("mailing_tube", episodes=3, start_episode=8),
            ),
            allow_evaluation_only=False,
        )
        self.assertEqual(
            [(item.profile_id, item.local_index) for item in plan],
            [
                ("micro_box", 5),
                ("mailing_tube", 8),
                ("mailing_tube", 9),
                ("mailing_tube", 10),
            ],
        )
        self.assertEqual(len({item.episode_index for item in plan}), 4)

    def test_duplicate_profile_requests_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            build_profile_episode_plan(
                self.config.parcel_profiles,
                (
                    CollectionRequest("micro_box", episodes=1, start_episode=0),
                    CollectionRequest("micro_box", episodes=1, start_episode=1),
                ),
            )

    def test_catalog_namespace_rejects_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            catalog_episode_index(-1, 0)


if __name__ == "__main__":
    unittest.main()
