from __future__ import annotations

import unittest

from parcel_sorter.finger_constraint_repro import (
    compare_finger_constraint_reproductions,
    partition_dynamic_control_inputs,
    summarize_finger_constraint_repro,
    validate_dynamic_control_replay_source_events,
    validate_dynamic_replay_source_events,
)


def _event(
    step: int,
    *,
    force_n: float = 5.0,
    penetration_m: float = 0.0002,
) -> dict[str, object]:
    return {
        "control_step": step,
        "physics_substep": 0,
        "parcel_contact_count": 1,
        "bilateral_parcel_contact": True,
        "peak_parcel_contact_force_n": force_n,
        "finger_dof_position_m": [0.03, 0.03],
        "finger_dof_velocity_m_s": [0.0, 0.0],
        "finger_actual_force_n": [-20.0, -20.0],
        "finger_control_force_n": [-20.0, -20.0],
        "contacts": [
            {
                "geom_a": {
                    "entity_role": "robot",
                    "link_name": "left_finger",
                    "geom_role": "stock_finger_collision_0",
                },
                "geom_b": {
                    "entity_role": "parcel",
                    "link_name": "box_baselink",
                    "geom_role": "collision_0",
                },
                "force_magnitude_n": force_n,
                "penetration_m": penetration_m,
            }
        ],
    }


def _payload(variant: str, events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "complete",
        "variant": variant,
        "contract": {
            "force_difference_n": 1.0,
            "finger_position_difference_m": 0.0001,
            "finger_velocity_difference_m_s": 0.01,
            "finger_force_difference_n": 1.0,
        },
        "events": events,
        "summary": summarize_finger_constraint_repro(
            events,
            force_abort_n=35.0,
            penetration_limit_m=0.001,
        ),
    }


class FingerConstraintReproTests(unittest.TestCase):
    def test_summary_marks_force_or_penetration_as_numerical_failure(self) -> None:
        force = summarize_finger_constraint_repro(
            [_event(0, force_n=36.0)],
            force_abort_n=35.0,
            penetration_limit_m=0.001,
        )
        penetration = summarize_finger_constraint_repro(
            [_event(0, penetration_m=0.002)],
            force_abort_n=35.0,
            penetration_limit_m=0.001,
        )

        self.assertTrue(force["numerical_safety_failure"])
        self.assertTrue(penetration["numerical_safety_failure"])
        self.assertEqual(penetration["first_penetration_limit"]["control_step"], 0)

    def test_comparison_classifies_mass_aware_only_failure(self) -> None:
        reference = _payload(
            "stock_explicit_inertia_ablation",
            [_event(0)],
        )
        candidate = _payload(
            "combined_rigid_body",
            [_event(0, force_n=40.0)],
        )

        result = compare_finger_constraint_reproductions(reference, candidate)

        self.assertEqual(result["conclusion"], "mass_aware_instability_reproduced")

    def test_comparison_rejects_failed_reference(self) -> None:
        reference = _payload(
            "stock_explicit_inertia_ablation",
            [_event(0, penetration_m=0.002)],
        )
        candidate = _payload("combined_rigid_body", [_event(0)])

        result = compare_finger_constraint_reproductions(reference, candidate)

        self.assertEqual(result["conclusion"], "invalid_reference")

    def test_dynamic_source_requires_consecutive_complete_state(self) -> None:
        events = []
        for substep in (0, 1):
            event = _event(196)
            event["physics_substep"] = substep
            event.update(
                {
                    "robot_qpos": [0.0] * 9,
                    "robot_dof_velocity": [0.0] * 9,
                    "robot_dof_actual_force_n": [0.0] * 9,
                    "robot_dof_control_force_n": [0.0] * 9,
                    "parcel_qpos": [0.0] * 7,
                    "parcel_dof_velocity": [0.0] * 6,
                }
            )
            events.append(event)

        result = validate_dynamic_replay_source_events(
            events,
            expected_start=(196, 0),
        )

        self.assertEqual(len(result), 2)
        events[1]["physics_substep"] = 2
        with self.assertRaisesRegex(ValueError, "must be consecutive"):
            validate_dynamic_replay_source_events(
                events,
                expected_start=(196, 0),
            )

    def test_dynamic_control_source_partitions_mode_specific_targets(self) -> None:
        events = []
        for substep in (0, 1):
            event = _event(196)
            event["physics_substep"] = substep
            event.update(
                {
                    "robot_qpos": [0.0] * 9,
                    "robot_dof_velocity": [0.0] * 9,
                    "robot_dof_actual_force_n": [0.0] * 9,
                    "robot_dof_control_force_n": [0.0] * 9,
                    "parcel_qpos": [0.0] * 7,
                    "parcel_dof_velocity": [0.0] * 6,
                    "robot_dof_control_mode": [0] * 7 + [2, 2],
                    "robot_dof_position_target": list(range(9)),
                    "robot_dof_velocity_target": [0.0] * 9,
                    "robot_dof_force_target_n": [0.0] * 7 + [-20.0, -20.0],
                }
            )
            events.append(event)

        validated = validate_dynamic_control_replay_source_events(
            events,
            expected_start=(196, 0),
        )
        grouped = partition_dynamic_control_inputs(validated[0])

        self.assertEqual(grouped["position"]["dof_indices"], tuple(range(7)))
        self.assertEqual(grouped["position"]["targets"], tuple(range(7)))
        self.assertEqual(grouped["force"]["dof_indices"], (7, 8))
        self.assertEqual(grouped["force"]["targets"], (-20.0, -20.0))
        self.assertEqual(grouped["velocity"]["dof_indices"], ())

        events[1]["robot_dof_control_mode"] = [0] * 8 + [3]
        with self.assertRaisesRegex(ValueError, "unsupported Genesis control mode"):
            validate_dynamic_control_replay_source_events(
                events,
                expected_start=(196, 0),
            )


if __name__ == "__main__":
    unittest.main()
