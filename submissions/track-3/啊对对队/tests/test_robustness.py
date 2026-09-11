from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.robustness import sample_for_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RobustnessProfileTests(unittest.TestCase):
    def test_unseen_profile_exceeds_training_ranges(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        sample = sample_for_profile(config, 2, "unseen")
        self.assertGreater(sample.mass_kg, config.randomization.parcel_mass_kg_max)
        self.assertGreater(sample.action_delay_steps, config.randomization.action_delay_steps_max)

    def test_nominal_profile_removes_noise_and_delay(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        sample = sample_for_profile(config, 3, "nominal")
        self.assertEqual(sample.size_scale_xyz, (1.0, 1.0, 1.0))
        self.assertEqual(sample.camera_noise_xyz_m, (0.0, 0.0, 0.0))
        self.assertEqual(sample.action_delay_steps, 0)


if __name__ == "__main__":
    unittest.main()
