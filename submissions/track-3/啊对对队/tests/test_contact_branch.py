import unittest

from parcel_sorter.contact_branch import (
    compare_contact_branch_events,
    summarize_contact_branch_events,
)


def _geom(entity: str, link: str, role: str) -> dict[str, str]:
    return {"entity_role": entity, "link_name": link, "geom_role": role}


def _event(
    step: int,
    substep: int,
    *,
    force: float = 5.0,
    bilateral: bool = True,
    contact_count: int = 2,
    velocity: tuple[float, float] = (0.0, 0.0),
    actual: tuple[float, float] = (2.0, -2.0),
    control: tuple[float, float] = (3.0, -3.0),
) -> dict[str, object]:
    return {
        "control_step": step,
        "physics_substep": substep,
        "parcel_contact_count": contact_count,
        "bilateral_parcel_contact": bilateral,
        "peak_parcel_contact_force_n": force,
        "finger_dof_position_m": [0.01, 0.01],
        "finger_dof_velocity_m_s": list(velocity),
        "finger_actual_force_n": list(actual),
        "finger_control_force_n": list(control),
        "contacts": (
            [
                {
                    "geom_a": _geom("robot", "left_finger", "adapter_collision"),
                    "geom_b": _geom("parcel", "base_link", "primitive_0"),
                    "force_magnitude_n": force,
                    "penetration_m": 0.0004,
                }
            ]
            if contact_count
            else []
        ),
    }


class ContactBranchTests(unittest.TestCase):
    def test_summary_reports_first_loss_abort_peak_and_finger_forces(self) -> None:
        events = [
            _event(202, 7),
            _event(
                203,
                0,
                force=38.0,
                bilateral=False,
                contact_count=19,
                velocity=(1.5, -2.5),
                actual=(12.0, -15.0),
                control=(18.0, -21.0),
            ),
        ]

        result = summarize_contact_branch_events(events, 35.0)

        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["first_bilateral_support_loss"]["control_step"], 203)
        self.assertEqual(result["first_force_abort"]["force_n"], 38.0)
        self.assertEqual(result["peak_force_contact"]["force_magnitude_n"], 38.0)
        self.assertEqual(result["maximum_contact_penetration_m"], 0.0004)
        self.assertEqual(result["finger_max_abs_velocity_m_s"], [1.5, 2.5])
        self.assertEqual(result["finger_max_abs_actual_force_n"], [12.0, 15.0])
        self.assertEqual(result["finger_max_abs_control_force_n"], [18.0, 21.0])

    def test_comparison_reports_preregistered_first_divergences(self) -> None:
        reference = [_event(202, 7), _event(203, 0, force=6.0)]
        candidate = [
            _event(202, 7),
            _event(203, 0, force=38.0, bilateral=False, contact_count=19),
        ]

        result = compare_contact_branch_events(reference, candidate)

        self.assertEqual(result["aligned_sample_count"], 2)
        self.assertEqual(result["first_divergence"]["control_step"], 203)
        self.assertEqual(
            result["first_divergence_by_signal"]["parcel_peak_force"][
                "max_abs_difference"
            ],
            32.0,
        )

    def test_summary_marks_complete_contact_loss_after_bilateral_support(self) -> None:
        events = [
            _event(203, 4, bilateral=True, contact_count=2),
            _event(203, 5, bilateral=False, contact_count=0),
            _event(203, 6, bilateral=False, contact_count=19),
        ]

        result = summarize_contact_branch_events(events, 35.0)

        self.assertEqual(
            result["first_bilateral_support_loss"],
            {"control_step": 203, "physics_substep": 5},
        )

    def test_comparison_rejects_duplicate_sample_keys(self) -> None:
        duplicate = [_event(202, 7), _event(202, 7)]

        with self.assertRaisesRegex(ValueError, "duplicate sample 202/7"):
            compare_contact_branch_events(duplicate, [_event(202, 7)])

    def test_empty_summary_is_explicit(self) -> None:
        result = summarize_contact_branch_events([], 35.0)

        self.assertEqual(result["status"], "no_samples")


if __name__ == "__main__":
    unittest.main()
