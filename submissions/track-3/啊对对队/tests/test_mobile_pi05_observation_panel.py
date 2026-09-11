import unittest

from parcel_sorter.mobile_pi05_observation_panel import (
    physical_context_signature,
    validate_pi05_observation_panel,
)


def _profile():
    return {
        "profile_id": "can",
        "shape": "cylinder",
        "orientation_mode": "upright",
        "handling_class": "parallel_jaw",
        "dimensions_min_m": [0.04, 0.04, 0.06],
        "dimensions_max_m": [0.07, 0.07, 0.16],
        "mass_kg_min": 0.1,
        "mass_kg_max": 0.8,
    }


class MobilePI05ObservationPanelTests(unittest.TestCase):
    def test_rejects_training_context_overlap(self) -> None:
        episodes = []
        for index in range(4):
            size = 0.045 + index * 0.005
            episodes.append(
                {
                    "episode_id": f"held-{index}",
                    "profile": "can",
                    "shape": "cylinder",
                    "orientation_mode": "upright",
                    "handling_class": "parallel_jaw",
                    "grasp_mode": "side_suction",
                    "size_m": [size, size, 0.08 + index * 0.01],
                    "mass_kg": 0.2 + index * 0.1,
                    "task_text": "Move the parcel.",
                }
            )
        panel = {
            "split": "heldout_observation_do_not_train",
            "minimum_observations_per_mode": 1,
            "episodes": episodes,
        }
        training = {physical_context_signature(episodes[0])}
        with self.assertRaisesRegex(ValueError, "overlaps"):
            validate_pi05_observation_panel(panel, {"can": _profile()}, training)

    def test_rejects_mode_label_leakage(self) -> None:
        profiles = {
            "can": _profile(),
            "box": {
                "shape": "box",
                "orientation_mode": "yaw",
                "handling_class": "parallel_jaw",
                "dimensions_min_m": [0.08, 0.04, 0.03],
                "dimensions_max_m": [0.2, 0.1, 0.1],
                "mass_kg_min": 0.1,
                "mass_kg_max": 1.0,
            },
            "tube": {
                "shape": "cylinder",
                "orientation_mode": "horizontal",
                "handling_class": "cradle_required",
                "dimensions_min_m": [0.3, 0.08, 0.08],
                "dimensions_max_m": [0.7, 0.16, 0.16],
                "mass_kg_min": 0.2,
                "mass_kg_max": 4.0,
            },
        }
        episodes = [
            {
                "episode_id": "top",
                "profile": "box",
                "shape": "box",
                "orientation_mode": "yaw",
                "handling_class": "parallel_jaw",
                "grasp_mode": "top_suction",
                "size_m": [0.12, 0.06, 0.05],
                "mass_kg": 0.3,
                "task_text": "Move the parcel.",
            },
            {
                "episode_id": "side",
                "profile": "can",
                "shape": "cylinder",
                "orientation_mode": "upright",
                "handling_class": "parallel_jaw",
                "grasp_mode": "side_suction",
                "size_m": [0.05, 0.05, 0.1],
                "mass_kg": 0.3,
                "task_text": "Use side_suction.",
            },
            {
                "episode_id": "cradle",
                "profile": "tube",
                "shape": "cylinder",
                "orientation_mode": "horizontal",
                "handling_class": "cradle_required",
                "grasp_mode": "cooperative_cradle",
                "size_m": [0.5, 0.1, 0.1],
                "mass_kg": 1.0,
                "task_text": "Move the parcel.",
            },
        ]
        panel = {
            "split": "heldout_observation_do_not_train",
            "minimum_observations_per_mode": 1,
            "episodes": episodes,
        }
        with self.assertRaisesRegex(ValueError, "leaks"):
            validate_pi05_observation_panel(panel, profiles, set())


if __name__ == "__main__":
    unittest.main()
