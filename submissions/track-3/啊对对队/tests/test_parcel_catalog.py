from collections import Counter
from dataclasses import replace
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.genesis_env import needs_rolling_friction, parcel_spawn_spec
from parcel_sorter.randomization import DomainRandomizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ParcelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(PROJECT_ROOT / "configs" / "catalog_v1.toml")
        self.randomizer = DomainRandomizer(
            self.config.randomization,
            self.config.seed,
            self.config.parcel_profiles,
        )

    def test_training_block_has_exact_predeclared_mix(self) -> None:
        counts = Counter(
            self.randomizer.sample(index).profile_id
            for index in range(self.config.randomization.catalog_block_size)
        )

        self.assertEqual(
            counts,
            Counter(
                {
                    profile.profile_id: round(
                        profile.selection_weight
                        * self.config.randomization.catalog_block_size
                    )
                    for profile in self.config.parcel_profiles
                    if not profile.evaluation_only
                }
            ),
        )

    def test_profile_dimensions_stay_inside_declared_ranges(self) -> None:
        profile = next(item for item in self.config.parcel_profiles if item.profile_id == "long_box")
        sample = self.randomizer.sample_profile(profile.profile_id, 123)

        self.assertEqual(sample.shape, "box")
        self.assertTrue(
            all(
                lower <= value <= upper
                for lower, value, upper in zip(
                    profile.dimensions_min_m,
                    sample.dimensions_m,
                    profile.dimensions_max_m,
                    strict=True,
                )
            )
        )

    def test_real_carrier_profile_remains_evaluation_only(self) -> None:
        sample = self.randomizer.sample_profile("usps_medium_flat_rate", 7)

        self.assertEqual(sample.handling_class, "suction_required")
        self.assertEqual(sample.dimensions_m, (0.28575, 0.22225, 0.1524))

    def test_horizontal_tube_maps_to_cylinder_axis(self) -> None:
        sample = self.randomizer.sample_profile("mailing_tube", 8)
        spec = parcel_spawn_spec(self.config, sample)

        self.assertEqual(spec.shape, "cylinder")
        self.assertEqual(spec.euler_degrees[1], 90.0)
        self.assertAlmostEqual(spec.cylinder_height_m, sample.dimensions_m[0])
        self.assertAlmostEqual(spec.cylinder_radius_m, sample.dimensions_m[1] / 2)
        self.assertAlmostEqual(spec.initial_z_m, spec.cylinder_radius_m)
        self.assertAlmostEqual(sample.dimensions_m[1], sample.dimensions_m[2])

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown parcel profile"):
            self.randomizer.sample_profile("not-real", 0)

    def test_catalog_v2_has_balanced_twenty_episode_mix(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        training = [profile for profile in config.parcel_profiles if not profile.evaluation_only]
        self.assertEqual(len(training), 12)
        self.assertEqual(
            sum(round(profile.selection_weight * config.randomization.catalog_block_size) for profile in training),
            config.randomization.catalog_block_size,
        )

    def test_catalog_v2_carrier_profiles_have_source_urls(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        carrier_profiles = [
            profile for profile in config.parcel_profiles if profile.profile_id.startswith("usps_")
        ]
        self.assertTrue(carrier_profiles)
        self.assertTrue(all(profile.evaluation_only for profile in carrier_profiles))
        self.assertTrue(all(profile.source_url.startswith("https://") for profile in carrier_profiles))

    def test_catalog_v2_covers_large_box_and_cylinder_boundaries(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        by_id = {profile.profile_id: profile for profile in config.parcel_profiles}
        training = [profile for profile in config.parcel_profiles if not profile.evaluation_only]
        evaluation = [profile for profile in config.parcel_profiles if profile.evaluation_only]

        self.assertEqual(len(training), 12)
        self.assertEqual(len(evaluation), 9)
        required = {
            "usps_large_flat_rate": ("box", "suction_required"),
            "large_rectangular_carton_boundary": ("box", "suction_required"),
            "large_square_carton_boundary": ("box", "suction_required"),
            "large_cylinder_boundary": ("cylinder", "cradle_required"),
        }

        for profile_id, expected in required.items():
            with self.subTest(profile_id=profile_id):
                profile = by_id[profile_id]
                self.assertEqual((profile.shape, profile.handling_class), expected)
                self.assertTrue(profile.evaluation_only)
                self.assertEqual(profile.selection_weight, 0.0)
                self.assertTrue(profile.source_url.startswith("https://"))

        self.assertGreater(by_id["large_rectangular_carton_boundary"].dimensions_max_m[0], 0.5)
        self.assertGreater(by_id["large_square_carton_boundary"].dimensions_max_m[1], 0.4)
        self.assertGreater(by_id["large_cylinder_boundary"].dimensions_max_m[0], 0.7)

    def test_horizontal_tube_has_explicit_rolling_resistance_candidate(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        profile = next(item for item in config.parcel_profiles if item.profile_id == "mailing_tube")
        sample = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles).sample_profile(
            profile.profile_id,
            0,
        )
        self.assertGreater(profile.rolling_friction, 0.0)
        self.assertAlmostEqual(sample.rolling_friction, profile.rolling_friction)
        self.assertTrue(needs_rolling_friction(sample))
        self.assertAlmostEqual(sample.final_approach_step_m or 0.0, 0.005)
        self.assertAlmostEqual(sample.lift_step_m or 0.0, 0.01)
        self.assertAlmostEqual(sample.finger_friction or 0.0, 2.0)
        self.assertAlmostEqual(sample.pregrasp_tolerance_m or 0.0, 0.01)
        self.assertEqual(sample.grasp_stability_steps, 3)

    def test_profile_rejects_nonpositive_lift_step(self) -> None:
        profile = next(item for item in self.config.parcel_profiles if item.profile_id == "mailing_tube")

        with self.assertRaisesRegex(ValueError, "lift_step_m"):
            replace(profile, lift_step_m=0.0).validate()

    def test_profile_rejects_finger_friction_outside_genesis_range(self) -> None:
        profile = next(item for item in self.config.parcel_profiles if item.profile_id == "mailing_tube")

        for invalid in (0.0, 5.1):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "finger_friction"):
                    replace(profile, finger_friction=invalid).validate()

    def test_profile_rejects_nonpositive_pregrasp_tolerance(self) -> None:
        profile = next(item for item in self.config.parcel_profiles if item.profile_id == "mailing_tube")

        with self.assertRaisesRegex(ValueError, "pregrasp_tolerance_m"):
            replace(profile, pregrasp_tolerance_m=0.0).validate()

    def test_profile_rejects_nonpositive_grasp_stability_steps(self) -> None:
        profile = next(item for item in self.config.parcel_profiles if item.profile_id == "mailing_tube")

        with self.assertRaisesRegex(ValueError, "grasp_stability_steps"):
            replace(profile, grasp_stability_steps=0).validate()

    def test_box_does_not_enable_rolling_solver_path(self) -> None:
        sample = self.randomizer.sample_profile("small_carton", 0)

        self.assertFalse(needs_rolling_friction(sample))


if __name__ == "__main__":
    unittest.main()
