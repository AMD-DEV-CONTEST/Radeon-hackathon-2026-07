from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.randomization import DomainRandomizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DomainRandomizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")

    def test_same_episode_is_reproducible(self) -> None:
        randomizer = DomainRandomizer(self.config.randomization, self.config.seed)
        self.assertEqual(randomizer.sample(7), randomizer.sample(7))

    def test_samples_stay_inside_configured_ranges(self) -> None:
        cfg = self.config.randomization
        sample = DomainRandomizer(cfg, self.config.seed).sample(11)
        self.assertTrue(all(cfg.parcel_size_scale_min <= value <= cfg.parcel_size_scale_max for value in sample.size_scale_xyz))
        self.assertTrue(cfg.parcel_mass_kg_min <= sample.mass_kg <= cfg.parcel_mass_kg_max)
        self.assertTrue(cfg.friction_min <= sample.friction <= cfg.friction_max)
        self.assertTrue(cfg.parcel_position_x_min <= sample.position_xy[0] <= cfg.parcel_position_x_max)
        self.assertTrue(cfg.parcel_position_y_min <= sample.position_xy[1] <= cfg.parcel_position_y_max)


if __name__ == "__main__":
    unittest.main()
