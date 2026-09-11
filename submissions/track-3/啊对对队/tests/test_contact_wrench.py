from __future__ import annotations

import unittest

from parcel_sorter.contact_wrench import (
    ContactPoint,
    ContactWrenchConfig,
    evaluate_contact_wrench,
    evaluate_contact_wrench_torch,
    summarize_contact_wrench_events,
)


def _config(**overrides: float) -> ContactWrenchConfig:
    values = {
        "parcel_mass_kg": 0.5,
        "parcel_dimensions_m": (0.20, 0.08, 0.10),
        "friction_coefficient": 1.0,
        "max_contact_force_n": 35.0,
        "transport_acceleration_m_s2": 1.5,
    }
    values.update(overrides)
    return ContactWrenchConfig(**values)


def _balanced_contacts() -> tuple[ContactPoint, ContactPoint]:
    return (
        ContactPoint(
            finger_id="left_finger",
            position_world_m=(-0.04, 0.0, 0.0),
            force_on_parcel_world_n=(10.0, 0.0, 2.4525),
            normal_world=(-1.0, 0.0, 0.0),
        ),
        ContactPoint(
            finger_id="right_finger",
            position_world_m=(0.04, 0.0, 0.0),
            force_on_parcel_world_n=(-10.0, 0.0, 2.4525),
            normal_world=(-1.0, 0.0, 0.0),
        ),
    )


class ContactWrenchTests(unittest.TestCase):
    def test_balanced_bilateral_grasp_has_finite_positive_quality(self) -> None:
        quality = evaluate_contact_wrench(_balanced_contacts(), (0.0, 0.0, 0.0), _config())

        self.assertTrue(quality.finite)
        self.assertTrue(quality.bilateral_contact)
        self.assertTrue(quality.robust)
        self.assertAlmostEqual(quality.net_force_residual_n, 0.0, places=6)
        self.assertAlmostEqual(quality.net_torque_residual_nm, 0.0, places=6)
        self.assertGreater(quality.quality_score, 0.0)
        self.assertLessEqual(quality.quality_score, 1.0)

    def test_unilateral_contact_cannot_be_robust(self) -> None:
        quality = evaluate_contact_wrench(
            _balanced_contacts()[:1],
            (0.0, 0.0, 0.0),
            _config(),
        )

        self.assertFalse(quality.bilateral_contact)
        self.assertFalse(quality.robust)
        self.assertEqual(quality.quality_score, 0.0)

    def test_friction_cone_violation_is_rejected(self) -> None:
        contacts = tuple(
            ContactPoint(
                finger_id=contact.finger_id,
                position_world_m=contact.position_world_m,
                force_on_parcel_world_n=(
                    contact.force_on_parcel_world_n[0],
                    0.0,
                    8.0,
                ),
                normal_world=contact.normal_world,
            )
            for contact in _balanced_contacts()
        )
        quality = evaluate_contact_wrench(
            contacts,
            (0.0, 0.0, 0.0),
            _config(friction_coefficient=0.5),
        )

        self.assertLess(quality.minimum_friction_margin_n, 0.0)
        self.assertEqual(quality.friction_cone_score, 0.0)
        self.assertFalse(quality.robust)

    def test_opposite_normal_conventions_produce_the_same_result(self) -> None:
        contacts = list(_balanced_contacts())
        right = contacts[1]
        contacts[1] = ContactPoint(
            finger_id=right.finger_id,
            position_world_m=right.position_world_m,
            force_on_parcel_world_n=right.force_on_parcel_world_n,
            normal_world=(1.0, 0.0, 0.0),
        )

        expected = evaluate_contact_wrench(
            _balanced_contacts(), (0.0, 0.0, 0.0), _config()
        )
        actual = evaluate_contact_wrench(contacts, (0.0, 0.0, 0.0), _config())
        self.assertAlmostEqual(actual.quality_score, expected.quality_score)

    def test_torch_vectorization_matches_reference(self) -> None:
        try:
            import torch
        except ImportError:
            self.skipTest("PyTorch is validated in the Radeon environment")
        contacts = _balanced_contacts()
        expected = evaluate_contact_wrench(contacts, (0.0, 0.0, 0.0), _config())
        actual = evaluate_contact_wrench_torch(
            torch.tensor([contact.position_world_m for contact in contacts]),
            torch.tensor([contact.force_on_parcel_world_n for contact in contacts]),
            torch.tensor([contact.normal_world for contact in contacts]),
            torch.tensor([0, 1]),
            torch.tensor((0.0, 0.0, 0.0)),
            _config(),
            torch,
        )

        for key, expected_value in expected.to_dict().items():
            actual_value = actual.to_dict()[key]
            if isinstance(expected_value, float):
                self.assertAlmostEqual(actual_value, expected_value, places=5, msg=key)
            else:
                self.assertEqual(actual_value, expected_value, key)

    def test_summary_uses_fixed_early_loaded_window(self) -> None:
        base = {
            "bilateral_contact": True,
            "robust": True,
            "quality_score": 0.8,
            "minimum_friction_margin_n": 2.0,
            "disturbance_force_margin_n": 1.0,
            "disturbance_torque_margin_nm": 0.1,
            "contact_center_offset_m": 0.01,
            "command": "hold",
            "parcel_lift_m": 0.0,
        }
        events = [dict(base) for _ in range(3)]
        events.extend(
            {
                **base,
                "command": "move_lift",
                "parcel_lift_m": 0.006,
                "quality_score": 0.7 - index * 0.1,
            }
            for index in range(3)
        )

        summary = summarize_contact_wrench_events(
            events,
            predictive_window_samples=2,
        )

        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["first_early_loaded_event_index"], 3)
        self.assertEqual(summary["prelift_settle"]["samples"], 2)
        self.assertEqual(summary["early_loaded"]["samples"], 2)
        self.assertAlmostEqual(summary["early_loaded"]["quality_score_mean"], 0.65)

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            _config(friction_coefficient=0.0).validate()


if __name__ == "__main__":
    unittest.main()
