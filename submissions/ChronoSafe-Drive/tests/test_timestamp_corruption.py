"""Pure NumPy checks for timestamp metadata corruption and augmentation."""

from __future__ import annotations

import unittest

import numpy as np

from chronosafe.timestamp_corruption import (
    STRESS_CALIBRATION_CONDITIONS,
    TRAINING_CONDITIONS,
    augment_timestamp_training_sequences,
    corrupt_timestamp_sequences,
    timestamp_feature_indices,
)


FEATURE_NAMES = [
    "camera_age_normalized",
    "lidar_age_normalized",
    "sensor_age_skew",
    "semantic_feature",
]


def sample_sequences(count: int = 20, length: int = 8) -> np.ndarray:
    source = np.zeros((count, length, len(FEATURE_NAMES)), dtype=np.float32)
    source[:, :, 0] = np.linspace(0.0, 0.8, length, dtype=np.float32)
    source[:, :, 1] = np.linspace(0.2, 1.0, length, dtype=np.float32)
    source[:, :, 2] = np.abs(source[:, :, 0] - source[:, :, 1])
    source[:, :, 3] = 7.0
    return source


class TimestampCorruptionTest(unittest.TestCase):
    def test_required_feature_indices(self) -> None:
        self.assertEqual(timestamp_feature_indices(FEATURE_NAMES), (0, 1, 2))
        with self.assertRaises(ValueError):
            timestamp_feature_indices(FEATURE_NAMES[1:])

    def test_all_registered_conditions_are_finite_and_shape_preserving(self) -> None:
        source = sample_sequences()
        for index, condition in enumerate(STRESS_CALIBRATION_CONDITIONS):
            with self.subTest(condition=condition):
                output = corrupt_timestamp_sequences(
                    source, FEATURE_NAMES, condition, np.random.default_rng(100 + index)
                )
                self.assertEqual(output.shape, source.shape)
                self.assertTrue(np.isfinite(output).all())
                np.testing.assert_array_equal(output[:, :, 3], source[:, :, 3])

    def test_augmentation_is_deterministic_and_counts_every_sequence(self) -> None:
        source = sample_sequences(count=100)
        first, first_counts = augment_timestamp_training_sequences(
            source, FEATURE_NAMES, probability=0.6, seed=2026
        )
        second, second_counts = augment_timestamp_training_sequences(
            source, FEATURE_NAMES, probability=0.6, seed=2026
        )
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first_counts, second_counts)
        self.assertEqual(sum(first_counts.values()), len(source))
        self.assertEqual(set(first_counts), {"intact", *TRAINING_CONDITIONS})
        np.testing.assert_array_equal(first[:, :, 3], source[:, :, 3])

    def test_probability_validation_and_no_augmentation(self) -> None:
        source = sample_sequences()
        output, counts = augment_timestamp_training_sequences(
            source, FEATURE_NAMES, probability=0.0, seed=2026
        )
        np.testing.assert_array_equal(output, source)
        self.assertEqual(counts["intact"], len(source))
        self.assertEqual(sum(counts.values()), len(source))
        for probability in (-0.01, 1.01):
            with self.assertRaises(ValueError):
                augment_timestamp_training_sequences(
                    source, FEATURE_NAMES, probability=probability, seed=2026
                )


if __name__ == "__main__":
    unittest.main()
