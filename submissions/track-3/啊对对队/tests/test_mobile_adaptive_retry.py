import unittest

from parcel_sorter.mobile_adaptive_retry import (
    EXPERT_RECOVERY,
    FORCE_RETREAT,
    NOMINAL_RECOVERY,
    PASH_ARM,
    PASH_BASE,
    PASH_DUAL_ARM,
    SEAL_SEARCH_PLUS_Y,
    EpisodicStrategyMemory,
    RecoveryRecipe,
    build_primitive_acquisition_manifest,
    choose_recovery_plan,
    choose_retry_strategy,
    classify_mobile_failure,
    strategy_context,
    summarize_adaptive_attempts,
)


class MobileAdaptiveRetryTests(unittest.TestCase):
    def test_classifies_force_before_task_gate(self) -> None:
        summary = {
            "success": False,
            "latched": False,
            "suction": {"max_contact_force_n": 35.0},
        }
        self.assertEqual(classify_mobile_failure(summary), "force_safety_abort")

    def test_first_causal_failure_separates_contact_latch_and_lift(self) -> None:
        base = {
            "success": False,
            "scene_stable": True,
            "lift_success": False,
            "transport_success": False,
            "placed_before_release": False,
            "released": False,
        }
        no_contact = {
            **base,
            "latched": False,
            "suction": {"max_contact_force_n": 0.0},
        }
        no_latch = {
            **base,
            "latched": False,
            "suction": {"max_contact_force_n": 2.0},
        }
        lost_lift = {
            **base,
            "latched": True,
            "suction": {"max_contact_force_n": 2.0},
        }

        self.assertEqual(classify_mobile_failure(no_contact), "contact_failure")
        self.assertEqual(classify_mobile_failure(no_latch), "suction_latch_failure")
        self.assertEqual(classify_mobile_failure(lost_lift), "lift_support_failure")

    def test_force_abort_permits_only_expert_recovery(self) -> None:
        memory = EpisodicStrategyMemory()
        selected = choose_retry_strategy(
            memory=memory,
            context="small_carton:medium:force_safety_abort",
            previous_failure="force_safety_abort",
            attempted_strategy_names=(PASH_ARM.name,),
        )
        self.assertEqual(selected, EXPERT_RECOVERY)

    def test_precision_failure_removes_arm_authority(self) -> None:
        memory = EpisodicStrategyMemory()
        selected = choose_retry_strategy(
            memory=memory,
            context="small_carton:medium:placement_success",
            previous_failure="placement_success",
        )
        self.assertEqual(selected, PASH_BASE)

    def test_cooperative_payload_selects_rigid_safe_dual_arm_projection(self) -> None:
        selected = choose_retry_strategy(
            memory=EpisodicStrategyMemory(),
            context="long_carton:medium:initial",
            previous_failure=None,
            cooperative_cradle=True,
        )
        self.assertEqual(selected, PASH_DUAL_ARM)
        self.assertTrue(selected.cooperative_safe)
        self.assertTrue(selected.depth_sidecar)

    def test_cooperative_precision_failure_removes_dual_arm_authority(self) -> None:
        selected = choose_retry_strategy(
            memory=EpisodicStrategyMemory(),
            context="long_carton:medium:placement_success",
            previous_failure="placement_success",
            cooperative_cradle=True,
        )
        self.assertEqual(selected, PASH_BASE)

    def test_recovery_plan_combines_safe_authority_and_parameter_recipe(self) -> None:
        initial = choose_recovery_plan(
            memory=EpisodicStrategyMemory(),
            context="small_carton:medium:initial",
            previous_failure=None,
        )
        self.assertEqual(initial.strategy, PASH_ARM)
        self.assertEqual(initial.recipe, NOMINAL_RECOVERY)
        seal_retry = choose_recovery_plan(
            memory=EpisodicStrategyMemory(),
            context="small_carton:medium:suction_latch",
            previous_failure="suction_latch",
        )
        self.assertEqual(seal_retry.strategy, PASH_BASE)
        self.assertEqual(seal_retry.recipe, SEAL_SEARCH_PLUS_Y)

    def test_force_abort_recovery_is_slow_expert_only(self) -> None:
        plan = choose_recovery_plan(
            memory=EpisodicStrategyMemory(),
            context="small_carton:medium:force_safety_abort",
            previous_failure="force_safety_abort",
        )
        self.assertEqual(plan.strategy, EXPERT_RECOVERY)
        self.assertEqual(plan.recipe, FORCE_RETREAT)
        self.assertEqual(plan.recipe.approach_speed_scale, 0.5)

    def test_recovery_recipe_rejects_unbounded_contact_search(self) -> None:
        with self.assertRaises(ValueError):
            RecoveryRecipe("unsafe", contact_offset_m=(0.009, 0.0))

    def test_memory_penalizes_force_aborts_and_retains_outcomes(self) -> None:
        context = strategy_context(
            profile="small_carton", mass_kg=0.5, previous_failure=None
        )
        memory = EpisodicStrategyMemory()
        memory.record(
            context=context, strategy=PASH_ARM, success=False, force_abort=True
        )
        memory.record(
            context=context, strategy=PASH_BASE, success=True, force_abort=False
        )
        selected = choose_retry_strategy(
            memory=memory, context=context, previous_failure=None
        )
        self.assertEqual(selected, PASH_BASE)
        payload = memory.to_dict()
        self.assertEqual(payload["contexts"][context][PASH_ARM.name]["force_aborts"], 1)
        self.assertEqual(
            payload["contexts"]["*:medium:initial"][PASH_BASE.name]["successes"], 1
        )

    def test_summary_separates_first_attempt_from_eventual_success(self) -> None:
        summary = summarize_adaptive_attempts(
            [
                {
                    "attempt_index": 0,
                    "summary_available": True,
                    "success": False,
                    "failure_stage": "lift_success",
                    "strategy": PASH_ARM.to_dict(),
                },
                {
                    "attempt_index": 1,
                    "summary_available": True,
                    "success": True,
                    "failure_stage": None,
                    "strategy": PASH_BASE.to_dict(),
                },
            ]
        )
        self.assertFalse(summary["first_attempt_success"])
        self.assertTrue(summary["eventual_success"])
        self.assertEqual(summary["attempts_to_success"], 2)
        self.assertEqual(summary["primitive_gaps"], ["lift_success"])

    def test_primitive_gap_recovery_becomes_audited_writeback_candidate(self) -> None:
        attempts = [
            {
                "attempt_index": 0,
                "summary_available": True,
                "summary": "attempt-1/summary.json",
                "success": False,
                "failure_stage": "suction_latch",
                "strategy": PASH_ARM.to_dict(),
            },
            {
                "attempt_index": 1,
                "summary_available": True,
                "summary": "attempt-2/summary.json",
                "success": True,
                "failure_stage": None,
                "strategy": PASH_BASE.to_dict(),
                "dataset": {
                    "saved": True,
                    "root": "attempt-2/recovery-dataset",
                    "frames": 600,
                },
            },
        ]
        manifest = build_primitive_acquisition_manifest(attempts)
        self.assertEqual(manifest["retraining_candidate_count"], 1)
        self.assertEqual(
            manifest["successful_acquisitions"][0]["primitive"], "suction_latch"
        )
        self.assertEqual(
            manifest["successful_acquisitions"][0]["writeback_status"],
            "eligible_after_dataset_audit",
        )
        self.assertEqual(
            manifest["successful_acquisitions"][0]["successful_dataset_frames"],
            600,
        )

    def test_summary_without_recorded_trajectory_is_not_retraining_data(self) -> None:
        attempts = [
            {
                "attempt_index": 0,
                "summary_available": True,
                "summary": "attempt-1/summary.json",
                "success": False,
                "failure_stage": "lift_success",
                "strategy": PASH_ARM.to_dict(),
            },
            {
                "attempt_index": 1,
                "summary_available": True,
                "summary": "attempt-2/summary.json",
                "success": True,
                "failure_stage": None,
                "strategy": PASH_BASE.to_dict(),
            },
        ]
        manifest = build_primitive_acquisition_manifest(attempts)
        self.assertEqual(manifest["retraining_candidate_count"], 0)
        self.assertEqual(
            manifest["successful_acquisitions"][0]["writeback_status"],
            "blocked_missing_trajectory",
        )


if __name__ == "__main__":
    unittest.main()
