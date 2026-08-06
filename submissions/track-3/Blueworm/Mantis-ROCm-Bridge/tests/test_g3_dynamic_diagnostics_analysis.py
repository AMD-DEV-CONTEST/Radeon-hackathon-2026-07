from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.analyze_g3_dynamic_diagnostics import (
    PHYSICAL_JOINT_NAMES,
    analyze_rows,
    write_outputs,
)


def _available(value: object) -> dict[str, object]:
    return {"available": True, "error": None, "value": value}


def _row(
    step: int,
    *,
    error: float = 0.0,
    collision: bool = False,
) -> dict[str, object]:
    action_index = step % 30
    before = 0 if action_index == 0 else 30 - action_index
    after = 29 - action_index
    contact = {
        "resolved_pair": (
            "bowl2:bowl_link <> "
            "mantis:right_wrist_yaw_link:source_mesh_collision"
        ),
        "label_a": "mantis:right_wrist_yaw_link:source_mesh_collision",
        "label_b": "bowl2:bowl_link",
        "geom_a": 17,
        "geom_b": 62,
        "forbidden_by_frozen_classifier": True,
        "fields": {
            "penetration": {
                "supported": True,
                "source": "penetration",
                "value": 0.0001,
                "error": None,
            }
        },
    }
    return {
        "schema_version": 1,
        "policy_step": step,
        "clock": {
            "policy_step": step,
            "policy_timestamp_s": step / 30.0,
            "observed_physics_hold_length": 8,
            "requested_physics_hold_length": 8,
            "simulator_step_before_hold": step * 8,
            "simulator_step_after_hold": (step + 1) * 8,
        },
        "act_queue": {
            "action_index_within_chunk": action_index,
            "chunk_sequence_index": step // 30,
            "chunk_size": 30,
            "select_action_call_index": step + 1,
            "queue_before_selection": {"length": before},
            "queue_after_selection": {"length": after},
        },
        "command_target_readback": {
            "full_physical_target_readback_18d": {
                "target_minus_readback_error": _available(
                    [error] + [0.0] * (len(PHYSICAL_JOINT_NAMES) - 1)
                )
            },
            "saturated_action_names": [],
        },
        "contact_state": {
            "bowls": [
                {
                    "entity_name": "bowl1",
                    "contacts": [],
                },
                {
                    "entity_name": "bowl2",
                    "contacts": [contact] if collision else [],
                },
                {
                    "entity_name": "bowl3",
                    "contacts": [],
                },
            ]
        },
        "kinematic_state": {
            "bowls": [
                {
                    "name": "bowl1",
                    "position_xyz_m": _available([0.0, 0.0, 0.7]),
                },
                {
                    "name": "bowl2",
                    "position_xyz_m": _available([0.2, 0.0, 0.7]),
                },
                {
                    "name": "bowl3",
                    "position_xyz_m": _available([-0.2, 0.0, 0.7]),
                },
            ],
            "robot_links": [
                {
                    "name": "right_wrist_yaw_link",
                    "position_xyz_m": _available(
                        [0.2, 0.1 - step * 0.01, 0.8]
                    ),
                }
            ],
        },
    }


class DynamicDiagnosticsAnalysisTest(unittest.TestCase):
    def test_timeout_replay_falsifies_clock_queue_drift(self) -> None:
        rows = [_row(index, error=0.01 * index) for index in range(4)]
        result = analyze_rows(
            rows,
            terminal_reason="timeout",
            terminal_policy_step=3,
            official_terminal_reason="timeout",
            official_terminal_policy_step=3,
        )
        self.assertTrue(result["clock_and_queue_audit"]["exact"])
        self.assertEqual(
            result["hypothesis_status"]["scheduler_or_queue_drift"],
            "falsified_in_observed_replay",
        )
        self.assertEqual(
            result["robot_bowl_contacts"]["contact_event_count"],
            0,
        )
        self.assertAlmostEqual(
            result["tracking"]["maximum_l2_error_rad"],
            0.03,
        )

    def test_collision_extracts_contact_and_reference_delta(self) -> None:
        rows = [_row(0), _row(1), _row(2, error=0.2, collision=True)]
        result = analyze_rows(
            rows,
            terminal_reason="collision_safety",
            terminal_policy_step=2,
            official_terminal_reason="collision_safety",
            official_terminal_policy_step=1,
        )
        self.assertEqual(
            result["terminal"]["policy_step_delta_from_official"],
            1,
        )
        self.assertEqual(
            result["robot_bowl_contacts"][
                "source_mesh_collision_event_count"
            ],
            1,
        )
        approach = result["link_origin_distance"][
            "collision_approach_last_three_ticks"
        ]
        self.assertIsNotNone(approach)
        self.assertGreater(approach["link_speed_m_s"], 0.0)
        self.assertEqual(
            result["tracking"]["terminal_joint_errors_descending"][0][
                "joint_name"
            ],
            "left_shoulder_pitch_joint",
        )

    def test_queue_mismatch_is_detected(self) -> None:
        rows = [_row(0), _row(1)]
        rows[1]["act_queue"]["queue_after_selection"]["length"] = 99
        result = analyze_rows(
            rows,
            terminal_reason="timeout",
            terminal_policy_step=1,
        )
        self.assertFalse(result["clock_and_queue_audit"]["exact"])
        self.assertGreater(
            result["clock_and_queue_audit"]["act_queue_mismatch_count"],
            0,
        )

    def test_output_is_non_overwriting_and_manifested(self) -> None:
        analysis = analyze_rows(
            [_row(0)],
            terminal_reason="timeout",
            terminal_policy_step=0,
        )
        analysis.update(
            {
                "seed": 101,
                "diagnostic_source_sha256": "a" * 64,
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "analysis"
            write_outputs(output, [analysis])
            self.assertTrue((output / "analysis_files.SHA256SUMS").is_file())
            with self.assertRaises(FileExistsError):
                write_outputs(output, [analysis])


if __name__ == "__main__":
    unittest.main()
