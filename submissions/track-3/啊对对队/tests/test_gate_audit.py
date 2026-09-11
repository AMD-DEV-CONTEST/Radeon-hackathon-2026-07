import unittest

from parcel_sorter.gate_audit import audit_reset_fallback_gate


def _episode(
    index: int,
    *,
    success: bool,
    force: float,
    active: bool,
    state_offset: float = 0.0,
) -> dict:
    return {
        "episode_index": index,
        "sample": {"episode_index": index, "profile_id": "box"},
        "result": {
            "success": success,
            "dropped": False,
            "max_contact_force_n": force,
        },
        "trace": [
            {
                "frame": 0,
                "stage": "approach",
                "command": "move_pregrasp",
                "retry_count": 0,
                "contact_force_n": 0.0,
                "ee_position_m": [0.5 + state_offset, 0.0, 0.2],
                "parcel_position_m": [0.4, 0.0, 0.05],
            },
            {
                "frame": 1,
                "stage": "complete" if success else "aborted",
                "command": "stop",
                "retry_count": 0,
                "contact_force_n": force,
                "ee_position_m": [0.5, 0.0, 0.2],
                "parcel_position_m": [0.4, 0.0, 0.05],
            },
        ],
        "safety_summary": {
            "grasp_planning_reset_fallback_gate_enabled": True,
            "grasp_planning_reset_fallback_gate_satisfied": active,
            "geometry_aware_grasp_planning_geometry_eligible": active,
            "geometry_aware_grasp_planning_active": active,
            "grasp_plan_attempts": 1 if active else 0,
            "grasp_plan_compute_ms_total": 5.0 if active else 0.0,
        },
    }


def _run(episodes: list[dict]) -> dict:
    return {
        "config": {"task": {"max_contact_force_n": 35.0}},
        "episodes": episodes,
    }


class ResetFallbackGateAuditTests(unittest.TestCase):
    def test_partitions_active_effects_from_inactive_execution_drift(self) -> None:
        baseline = _run(
            [
                _episode(0, success=False, force=50.0, active=False),
                _episode(1, success=True, force=10.0, active=False),
            ]
        )
        candidate = _run(
            [
                _episode(0, success=True, force=20.0, active=True),
                _episode(
                    1,
                    success=False,
                    force=40.0,
                    active=False,
                    state_offset=0.01,
                ),
            ]
        )

        result = audit_reset_fallback_gate(baseline, candidate)

        self.assertEqual(result["partition_episode_indices"]["planner_active"], [0])
        self.assertEqual(result["partition_episode_indices"]["planner_inactive"], [1])
        self.assertEqual(
            result["attribution"][
                "planner_active_success_discordant_episode_indices"
            ],
            [0],
        )
        self.assertEqual(
            result["attribution"][
                "planner_inactive_binary_outcome_drift_episode_indices"
            ],
            [1],
        )
        diagnostic = result["planner_inactive_trace_diagnostics"][0]
        self.assertEqual(diagnostic["first_state_divergence_frame"], 0)
        self.assertEqual(diagnostic["first_decision_divergence_frame"], 1)
        self.assertTrue(diagnostic["state_precedes_decision"])

    def test_rejects_attempts_from_an_inactive_planner(self) -> None:
        baseline = _run([_episode(0, success=True, force=10.0, active=False)])
        candidate_episode = _episode(0, success=True, force=10.0, active=False)
        candidate_episode["safety_summary"]["grasp_plan_attempts"] = 1

        with self.assertRaisesRegex(ValueError, "attempts while inactive"):
            audit_reset_fallback_gate(baseline, _run([candidate_episode]))


if __name__ == "__main__":
    unittest.main()
