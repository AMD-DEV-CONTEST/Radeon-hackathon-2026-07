import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "run_mobile_pi05_autonomous_recovery_rocm.py"
)
SPEC = importlib.util.spec_from_file_location(
    "run_mobile_pi05_autonomous_recovery_rocm", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MobilePI05AutonomousRecoveryTests(unittest.TestCase):
    def _command(self) -> list[str]:
        return MODULE.build_attempt_command(
            evaluator=Path("evaluate.py"),
            checkpoint=Path("checkpoint"),
            attempt_output=Path("attempt/run"),
            replay_root=Path("attempt/replay"),
            backend="rocm",
            policy_hz=3,
            chunk_execution_protocol="pi05-open-loop-queue-v1",
            chunk_execution_steps=10,
            retry_index=1,
            parcel_profile="small_carton",
            parcel_shape="box",
            parcel_orientation="yaw",
            parcel_yaw_rad=0.1,
            expected_grasp_mode="top_suction",
            minimum_sealed_cups=2,
            parcel_size_m=(0.2, 0.12, 0.2),
            parcel_mass_kg=0.4,
            parcel_friction=0.8,
            parcel_offset_m=(0.0, 0.0),
            task_text="pick and place the parcel",
            force_memory_harness=True,
            depth_risk_sidecar=True,
        )

    def test_command_forces_pi05_authority_and_has_no_expert_recovery_offset(self) -> None:
        command = self._command()
        rendered = " ".join(command)
        self.assertIn("--policy-mode pi05_residual", rendered)
        self.assertIn("--vla-routes-grasp-mode", command)
        self.assertIn("--require-vla-goal-verdict", command)
        self.assertIn("--record-pi05-residual-dataset", command)
        self.assertNotIn("--require-vla-grasp-mode", command)
        self.assertFalse(any(part.startswith("--recovery-") for part in command))

    def test_failure_feedback_is_observation_not_a_motion_recipe(self) -> None:
        task = MODULE.recovery_task_text(
            "pick and place the parcel", "suction_latch"
        )
        self.assertIn("did not form a stable suction seal", task)
        self.assertNotIn("top_suction", task)
        self.assertNotIn("side_suction", task)
        self.assertNotIn("cooperative_cradle", task)
        self.assertNotIn("0.00", task)

    def test_physical_success_without_replay_admission_is_not_success(self) -> None:
        result = MODULE.summarize_attempts(
            [
                {
                    "attempt_index": 0,
                    "summary_available": True,
                    "physical_success": True,
                    "vla_qualified_success": False,
                    "expert_fallback_count": 1,
                    "emergency_stop_count": 0,
                    "force_violation_count": 0,
                    "policy_authority": "hybrid_expert_reference_plus_vla_residual",
                    "accepted_as_pure_vla_experience": False,
                    "replay_root": "attempt/replay",
                }
            ],
            checkpoint=Path("checkpoint"),
            maximum_attempts=3,
        )
        self.assertFalse(result["eventual_success"])
        self.assertEqual(result["vla_qualified_run_count"], 0)
        self.assertEqual(result["expert_fallback_count"], 1)

    def test_qualified_replay_is_eventual_pi05_success(self) -> None:
        result = MODULE.summarize_attempts(
            [
                {
                    "attempt_index": 0,
                    "summary_available": True,
                    "physical_success": False,
                    "vla_qualified_success": False,
                    "expert_fallback_count": 0,
                    "emergency_stop_count": 0,
                    "force_violation_count": 0,
                    "policy_authority": "hybrid_expert_reference_plus_vla_residual",
                    "accepted_as_pure_vla_experience": False,
                    "replay_root": "attempt-1/replay",
                },
                {
                    "attempt_index": 1,
                    "summary_available": True,
                    "physical_success": True,
                    "vla_qualified_success": True,
                    "expert_fallback_count": 0,
                    "emergency_stop_count": 0,
                    "force_violation_count": 0,
                    "policy_authority": "hybrid_expert_reference_plus_vla_residual",
                    "accepted_as_pure_vla_experience": False,
                    "replay_root": "attempt-2/replay",
                },
            ],
            checkpoint=Path("checkpoint"),
            maximum_attempts=3,
        )
        self.assertTrue(result["eventual_success"])
        self.assertFalse(result["first_attempt_success"])
        self.assertEqual(result["attempts_to_success"], 2)
        self.assertEqual(result["successful_replay_roots"], ["attempt-2/replay"])
        self.assertFalse(result["pure_vla_eventual_success"])


if __name__ == "__main__":
    unittest.main()
