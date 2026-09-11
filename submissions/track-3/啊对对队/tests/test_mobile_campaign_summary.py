import unittest

from scripts.summarize_mobile_vla_campaign import (
    _material_pi05_absolute,
    _material_pi05_residual,
    _profile_summaries,
    _vla_attribution_class,
    _vla_qualified,
)
from parcel_sorter.mobile_policy_attribution import (
    HYBRID_VLA_AUTHORITY,
    summarize_mobile_policy_attribution,
)


class MobileCampaignSummaryTests(unittest.TestCase):
    def test_reports_hybrid_residual_attribution_separately_from_fallback(self) -> None:
        policy = {
            "mode": "pi05_residual",
            "trace": [
                {
                    "policy_authority": "hybrid_expert_reference_plus_vla_residual",
                    "expert_reference_used": True,
                    "fallback_to_expert": False,
                }
            ],
        }
        self.assertEqual(
            _vla_attribution_class(policy),
            "hybrid_vla_residual_with_expert_reference",
        )
        self.assertEqual(
            summarize_mobile_policy_attribution(policy["trace"]).policy_authority,
            HYBRID_VLA_AUTHORITY,
        )

    def test_reports_absolute_vla_attribution(self) -> None:
        policy = {
            "trace": [
                {
                    "policy_authority": "absolute_vla_action_candidate",
                    "expert_reference_used": False,
                    "expert_reference_semantics": "expert_action_is_harness_fallback_only",
                    "task_routing_authority": "vla_policy",
                    "task_action_corrections": [],
                }
            ]
        }
        self.assertEqual(
            _vla_attribution_class(policy),
            "absolute_vla_action_with_harness_only",
        )
        self.assertTrue(
            summarize_mobile_policy_attribution(policy["trace"]).internally_consistent
        )

    def test_labels_external_stage_machine_as_shielded_vla(self) -> None:
        policy = {
            "trace": [
                {
                    "policy_authority": "absolute_vla_action_candidate",
                    "expert_reference_used": False,
                    "task_routing_authority": "external_stage_machine",
                    "task_action_corrections": [
                        "deterministic_release_interlock"
                    ],
                }
            ]
        }
        attribution = summarize_mobile_policy_attribution(policy["trace"])
        self.assertEqual(attribution.system_control_class, "shielded_vla")
        self.assertEqual(attribution.task_action_correction_count, 1)
        self.assertEqual(
            _vla_attribution_class(policy),
            "shielded_vla_external_routing_or_task_interlock",
        )

    def test_requires_true_pi05_routing_for_vla_qualification(self) -> None:
        policy = {
            "enabled": True,
            "checkpoint": "/checkpoint",
            "policy_type": "pi05",
            "mode": "pi05_residual",
            "vla_routes_grasp_mode": True,
            "grasp_mode_verdict_required": True,
            "goal_verdict_required": True,
            "goal_arrival_verified": True,
            "grasp_mode_match": True,
            "expected_grasp_mode": "side_suction",
            "selected_grasp_mode": "side_suction",
            "executed_grasp_mode": "side_suction",
            "applied_physics_steps": 10,
            "expert_fallback_count": 0,
        }
        self.assertTrue(_vla_qualified(policy, material_residual=True))
        policy["vla_routes_grasp_mode"] = False
        self.assertFalse(_vla_qualified(policy, material_residual=True))

    def test_rejects_zero_residual_or_expert_fallback_as_vla_qualified(self) -> None:
        policy = {
            "enabled": True,
            "checkpoint": "/checkpoint",
            "policy_type": "pi05",
            "mode": "pi05_residual",
            "vla_routes_grasp_mode": True,
            "grasp_mode_verdict_required": True,
            "goal_verdict_required": True,
            "goal_arrival_verified": True,
            "grasp_mode_match": True,
            "expected_grasp_mode": "top_suction",
            "selected_grasp_mode": "top_suction",
            "executed_grasp_mode": "top_suction",
            "applied_physics_steps": 10,
            "expert_fallback_count": 0,
        }
        self.assertFalse(_vla_qualified(policy, material_residual=False))
        policy["expert_fallback_count"] = 1
        self.assertFalse(_vla_qualified(policy, material_residual=True))

    def test_detects_material_pi05_contact_residual(self) -> None:
        material, maximum = _material_pi05_residual(
            {
                "trace": [
                    {
                        "residual_projection": {
                            "base_residual": [0.0, 0.0, 0.0],
                            "left_contact_residual_m": [0.004, 0.0, 0.0],
                            "right_contact_residual_m": [0.0, 0.0, 0.0],
                        }
                    }
                ]
            }
        )
        self.assertTrue(material)
        self.assertAlmostEqual(maximum, 0.004)

    def test_qualifies_only_full_authority_absolute_vla(self) -> None:
        policy = {
            "enabled": True,
            "checkpoint": "/checkpoint",
            "policy_type": "pi05",
            "mode": "pi05_absolute",
            "vla_routes_grasp_mode": True,
            "grasp_mode_verdict_required": True,
            "goal_verdict_required": True,
            "goal_arrival_verified": True,
            "grasp_mode_match": True,
            "expected_grasp_mode": "top_suction",
            "selected_grasp_mode": "top_suction",
            "executed_grasp_mode": "top_suction",
            "applied_physics_steps": 10,
            "expert_fallback_count": 0,
            "emergency_stop_count": 0,
            "policy_authority": "absolute_vla_action_candidate",
            "system_control_class": "pure_vla",
            "task_action_correction_count": 0,
            "expert_reference_used": False,
            "absolute_full_authority": True,
            "transport_deadline_handoff": False,
        }
        self.assertTrue(
            _vla_qualified(
                policy,
                material_residual=False,
                material_absolute_action=True,
            )
        )
        policy["absolute_full_authority"] = False
        self.assertFalse(
            _vla_qualified(
                policy,
                material_residual=False,
                material_absolute_action=True,
            )
        )

    def test_detects_material_pi05_absolute_action(self) -> None:
        material, maximum = _material_pi05_absolute(
            {
                "trace": [
                    {
                        "raw_base_action": [0.03, 0.0, 0.0],
                        "arm_residual": {
                            "residual_norm_m": 0.01,
                            "right_residual_norm_m": 0.0,
                        },
                    }
                ]
            }
        )
        self.assertTrue(material)
        self.assertAlmostEqual(maximum, 0.03)

    def test_near_zero_pi05_residual_is_not_material(self) -> None:
        material, maximum = _material_pi05_residual(
            {
                "trace": [
                    {
                        "residual_projection": {
                            "left_contact_residual_m": [1e-8, 0.0, 0.0]
                        }
                    }
                ]
            }
        )
        self.assertFalse(material)
        self.assertAlmostEqual(maximum, 1e-8)

    def test_groups_success_and_failure_by_profile(self) -> None:
        runs = [
            {
                "profile": "small_carton",
                "success": True,
                "placement_error_m": 0.01,
                "failure_stage": None,
                "suction": {"max_contact_force_n": 4.0},
            },
            {
                "profile": "small_carton",
                "success": False,
                "placement_error_m": 0.20,
                "failure_stage": "lift_success",
                "suction": {"max_contact_force_n": 5.0},
            },
            {
                "profile": "flat_mailer",
                "success": True,
                "placement_error_m": 0.02,
                "failure_stage": None,
                "suction": {"max_contact_force_n": 3.0},
            },
        ]
        result = _profile_summaries(runs)
        self.assertEqual(result["small_carton"]["successes"], 1)
        self.assertEqual(result["small_carton"]["trials"], 2)
        self.assertEqual(
            result["small_carton"]["failure_stages"], {"lift_success": 1}
        )
        self.assertEqual(result["flat_mailer"]["success_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
