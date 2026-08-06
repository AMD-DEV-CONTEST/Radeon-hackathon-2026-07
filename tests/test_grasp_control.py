import unittest

import numpy as np
import simulation.grasp_control as grasp_control

from simulation.grasp_control import (
    ConvergenceWindow,
    classify_finger_contacts,
    local_point_world,
    quat_rotate_wxyz,
)


class TcpGeometryTests(unittest.TestCase):
    def test_local_point_is_rotated_before_translation(self):
        half = np.sqrt(0.5)
        actual = local_point_world(
            link_pos=[1.0, 2.0, 3.0],
            link_quat_wxyz=[half, 0.0, half, 0.0],
            local_point=[0.0, 0.0, -0.1],
        )
        np.testing.assert_allclose(actual, [0.9, 2.0, 3.0], atol=1e-9)

    def test_rejects_zero_norm_quaternion(self):
        with self.assertRaises(ValueError):
            quat_rotate_wxyz([0.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0])

    def test_rejects_non_finite_quaternion(self):
        with self.assertRaises(ValueError):
            quat_rotate_wxyz([np.nan, 0.0, 0.0, 1.0], [1.0, 0.0, 0.0])


class ConvergenceWindowTests(unittest.TestCase):
    def test_requires_consecutive_samples_and_resets_on_miss(self):
        window = ConvergenceWindow(tolerance=0.005, required_samples=3)
        self.assertFalse(window.update(0.004))
        self.assertFalse(window.update(0.003))
        self.assertFalse(window.update(0.006))
        self.assertFalse(window.update(0.002))
        self.assertFalse(window.update(0.002))
        self.assertTrue(window.update(0.001))

    def test_rejects_invalid_required_sample_counts(self):
        for required_samples in (0, -1, True, 1.5):
            with self.subTest(required_samples=required_samples):
                with self.assertRaises(ValueError):
                    ConvergenceWindow(tolerance=0.005, required_samples=required_samples)

    def test_rejects_negative_or_non_finite_tolerance(self):
        for tolerance in (-0.001, np.inf, -np.inf, np.nan):
            with self.subTest(tolerance=tolerance):
                with self.assertRaises(ValueError):
                    ConvergenceWindow(tolerance=tolerance, required_samples=3)


class _TorchLikeArray:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def detach(self):
        self.calls.append("detach")
        return self

    def cpu(self):
        self.calls.append("cpu")
        return self

    def numpy(self):
        self.calls.append("numpy")
        return self.values


class ContactClassificationTests(unittest.TestCase):
    def test_pad_classifier_rejects_gripper_housing_as_fixed_finger(self):
        self.assertTrue(hasattr(grasp_control, "classify_finger_pad_contacts"))
        contacts = {
            "geom_a": np.array([25, 27]),
            "geom_b": np.array([8, 8]),
            "link_a": np.array([19, 20]),
            "link_b": np.array([8, 8]),
            "force_a": np.array([[0.0, 2.0, 0.0], [0.0, 3.0, 4.0]]),
        }

        summary = grasp_control.classify_finger_pad_contacts(
            contacts, fixed_geom_idx=26, moving_geom_idx=27
        )

        self.assertFalse(summary.fixed)
        self.assertTrue(summary.moving)
        self.assertFalse(summary.bilateral)
        self.assertEqual(summary.count, 1)
        self.assertEqual(summary.max_force, 5.0)

    def test_pad_classifier_accepts_only_the_two_exact_pad_geoms(self):
        self.assertTrue(hasattr(grasp_control, "classify_finger_pad_contacts"))
        contacts = {
            "geom_a": np.array([25, 26, 27]),
            "geom_b": np.array([8, 8, 8]),
            "force_a": np.array(
                [[99.0, 0.0, 0.0], [3.0, 4.0, 0.0], [0.0, 0.0, 6.0]]
            ),
        }

        summary = grasp_control.classify_finger_pad_contacts(
            contacts, fixed_geom_idx=26, moving_geom_idx=27
        )

        self.assertTrue(summary.bilateral)
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.max_force, 6.0)

    def test_detects_bilateral_contacts_and_force(self):
        contacts = {
            "link_a": np.array([10, 30, 20]),
            "link_b": np.array([30, 10, 30]),
            "force_a": np.array(
                [[3.0, 4.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 6.0]]
            ),
            "force_b": np.zeros((3, 3)),
        }
        summary = classify_finger_contacts(
            contacts, fixed_link_idx=10, moving_link_idx=20
        )
        self.assertTrue(summary.fixed)
        self.assertTrue(summary.moving)
        self.assertTrue(summary.bilateral)
        self.assertEqual(summary.count, 3)
        self.assertEqual(summary.max_force, 6.0)

    def test_ignores_invalid_and_unrelated_contacts(self):
        contacts = {
            "link_a": np.array([10, 20, 40]),
            "link_b": np.array([30, 30, 30]),
            "force_a": np.ones((3, 3)),
            "force_b": -np.ones((3, 3)),
            "valid_mask": np.array([True, False, True]),
        }
        summary = classify_finger_contacts(
            contacts, fixed_link_idx=10, moving_link_idx=20
        )
        self.assertTrue(summary.fixed)
        self.assertFalse(summary.moving)
        self.assertFalse(summary.bilateral)
        self.assertEqual(summary.count, 2)

    def test_empty_contacts_are_not_a_grasp(self):
        summary = classify_finger_contacts({}, fixed_link_idx=10, moving_link_idx=20)
        self.assertFalse(summary.bilateral)
        self.assertEqual(summary.count, 0)

    def test_converts_torch_like_contact_arrays(self):
        link_a = _TorchLikeArray([10])
        link_b = _TorchLikeArray([30])
        force_a = _TorchLikeArray([[0.0, 0.0, 2.5]])
        summary = classify_finger_contacts(
            {"link_a": link_a, "link_b": link_b, "force_a": force_a},
            fixed_link_idx=10,
            moving_link_idx=20,
        )
        self.assertTrue(summary.fixed)
        self.assertEqual(summary.max_force, 2.5)
        for value in (link_a, link_b, force_a):
            self.assertEqual(value.calls, ["detach", "cpu", "numpy"])

    def test_flattens_single_environment_batched_contacts(self):
        summary = classify_finger_contacts(
            {
                "link_a": np.array([[10, 20]]),
                "link_b": np.array([[30, 30]]),
                "force_a": np.array([[[3.0, 4.0, 0.0], [0.0, 0.0, 6.0]]]),
                "valid_mask": np.array([[True, False]]),
            },
            fixed_link_idx=10,
            moving_link_idx=20,
        )
        self.assertTrue(summary.fixed)
        self.assertFalse(summary.moving)
        self.assertEqual(summary.count, 1)
        self.assertEqual(summary.max_force, 5.0)

    def test_rejects_mismatched_link_array_lengths(self):
        with self.assertRaisesRegex(ValueError, "link_a and link_b"):
            classify_finger_contacts(
                {"link_a": np.array([10, 20]), "link_b": np.array([30])},
                fixed_link_idx=10,
                moving_link_idx=20,
            )

    def test_rejects_mismatched_mask_and_tolerates_wrong_force_rows(self):
        contacts = {
            "link_a": np.array([10, 20]),
            "link_b": np.array([30, 30]),
            "valid_mask": np.array([True]),
            "force_a": np.ones((1, 3)),
        }
        with self.assertRaisesRegex(ValueError, "valid_mask"):
            classify_finger_contacts(contacts, fixed_link_idx=10, moving_link_idx=20)

        contacts.pop("valid_mask")
        summary = classify_finger_contacts(
            contacts, fixed_link_idx=10, moving_link_idx=20
        )
        self.assertEqual(summary.max_force, 0.0)

    def test_tolerates_empty_and_malformed_optional_force_data(self):
        contacts = {"link_a": np.array([10, 20]), "link_b": np.array([30, 30])}
        malformed_forces = (
            np.empty((0, 3)),
            np.ones((2, 2)),
            np.array([1.0, 2.0]),
            np.array([["invalid", "force", "data"]], dtype=object),
            np.array([[np.nan, 0.0, 0.0], [np.inf, 0.0, 0.0]]),
        )
        for force_a in malformed_forces:
            with self.subTest(force_a=force_a):
                summary = classify_finger_contacts(
                    {**contacts, "force_a": force_a},
                    fixed_link_idx=10,
                    moving_link_idx=20,
                )
                self.assertTrue(np.isfinite(summary.max_force))
                self.assertEqual(summary.max_force, 0.0)

    def test_ignores_force_when_all_contact_rows_are_invalid(self):
        summary = classify_finger_contacts(
            {
                "link_a": np.array([10, 20]),
                "link_b": np.array([30, 30]),
                "force_a": np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 6.0]]),
                "valid_mask": np.array([False, False]),
            },
            fixed_link_idx=10,
            moving_link_idx=20,
        )
        self.assertEqual(summary.max_force, 0.0)

    def test_uses_valid_force_b_when_force_a_is_malformed(self):
        summary = classify_finger_contacts(
            {
                "link_a": np.array([10, 20]),
                "link_b": np.array([30, 30]),
                "force_a": np.ones((2, 2)),
                "force_b": np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 6.0]]),
            },
            fixed_link_idx=10,
            moving_link_idx=20,
        )
        self.assertEqual(summary.max_force, 6.0)
