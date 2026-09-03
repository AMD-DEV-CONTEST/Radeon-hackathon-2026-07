from __future__ import annotations

import unittest

from tools.probe_g3_commanded_target_collision import (
    canonical_pair,
    classify_collision_pair,
    extract_recorded_configuration,
    forbidden_robot_bowl_pairs,
    robot_bowl_collision_family,
    serialize_detected_pairs,
)


def _available(value: object) -> dict[str, object]:
    return {"available": True, "error": None, "value": value}


class CommandedTargetCollisionProbeTest(unittest.TestCase):
    def test_extract_recorded_configuration(self) -> None:
        row = {
            "policy_step": 27,
            "command_target_readback": {
                "full_physical_target_readback_18d": {
                    "target": _available([0.1] * 18),
                    "readback": _available([0.09] * 18),
                }
            },
            "kinematic_state": {
                "bowls": [
                    {
                        "name": f"bowl{index}",
                        "position_xyz_m": _available([index, 0.0, 0.7]),
                        "quaternion_wxyz": _available(
                            [1.0, 0.0, 0.0, 0.0]
                        ),
                    }
                    for index in range(1, 4)
                ]
            },
            "contact_state": {
                "forbidden_collision_pairs": [
                    "bowl2:bowl_link <> "
                    "mantis:right_wrist_yaw_link:source_mesh_collision"
                ]
            },
        }
        result = extract_recorded_configuration(row)
        self.assertEqual(result["policy_step"], 27)
        self.assertEqual(len(result["target_18d"]), 18)
        self.assertEqual(sorted(result["bowls"]), ["bowl1", "bowl2", "bowl3"])
        self.assertEqual(len(result["logged_forbidden_pairs"]), 1)

    def test_pair_classification_preserves_frozen_clamp_rule(self) -> None:
        forbidden = classify_collision_pair(
            "mantis:right_wrist_yaw_link:source_mesh_collision",
            "bowl2:bowl_link",
        )
        allowed = classify_collision_pair(
            "mantis:right_clamp_left_link:source_mesh_collision",
            "bowl2:bowl_link",
        )
        self.assertEqual(forbidden["category"], "robot_bowl_forbidden")
        self.assertTrue(forbidden["forbidden_by_frozen_classifier"])
        self.assertEqual(allowed["category"], "robot_bowl_allowed_clamp")
        self.assertFalse(allowed["forbidden_by_frozen_classifier"])

    def test_serialization_is_canonical_and_deduplicated(self) -> None:
        labels = {
            17: "mantis:right_wrist_yaw_link:source_mesh_collision",
            62: "bowl2:bowl_link",
        }
        result = serialize_detected_pairs(
            [(62, 17), (17, 62)],
            labels,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["resolved_pair"],
            canonical_pair(labels[17], labels[62]),
        )
        self.assertEqual(
            forbidden_robot_bowl_pairs(result),
            [result[0]["resolved_pair"]],
        )

    def test_collision_family_ignores_wrist_axis_but_not_bowl(self) -> None:
        pitch = robot_bowl_collision_family(
            "bowl1:bowl_link <> "
            "mantis:right_wrist_pitch_link:source_mesh_collision"
        )
        yaw = robot_bowl_collision_family(
            "bowl1:bowl_link <> "
            "mantis:right_wrist_yaw_link:source_mesh_collision"
        )
        other_bowl = robot_bowl_collision_family(
            "bowl2:bowl_link <> "
            "mantis:right_wrist_yaw_link:source_mesh_collision"
        )
        self.assertEqual(pitch, yaw)
        self.assertNotEqual(pitch, other_bowl)

    def test_invalid_vector_fails_closed(self) -> None:
        row = {
            "policy_step": 0,
            "command_target_readback": {
                "full_physical_target_readback_18d": {
                    "target": _available([0.0] * 17),
                    "readback": _available([0.0] * 18),
                }
            },
            "kinematic_state": {"bowls": []},
            "contact_state": {"forbidden_collision_pairs": []},
        }
        with self.assertRaises(ValueError):
            extract_recorded_configuration(row)


if __name__ == "__main__":
    unittest.main()
