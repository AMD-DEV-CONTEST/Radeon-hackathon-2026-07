import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "run_mobile_pi05_chunk_runtime_ablation_rocm.py"
)
SPEC = importlib.util.spec_from_file_location("run_pi05_chunk_ablation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MobilePI05ChunkRuntimeAblationTests(unittest.TestCase):
    def test_campaign_command_uses_pure_absolute_pi05(self) -> None:
        command = MODULE._campaign_command(
            checkpoint=Path("checkpoint"),
            episode_config=Path("episodes.json"),
            output=Path("output"),
            arm={
                "chunk_execution_protocol": "pi05-open-loop-queue-v1",
                "chunk_execution_steps": 10,
            },
            policy_hz=3,
        )
        mode_index = command.index("--policy-mode")
        self.assertEqual(command[mode_index + 1], "pi05_absolute")

    def test_route_screen_must_belong_to_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            screen = {
                "status": "passed",
                "checkpoint": str(checkpoint),
                "metrics": {"probe_accuracy": 1.0, "fallback_count": 0},
            }
            MODULE._validate_route_screen(screen, checkpoint)

            other = Path(directory) / "other"
            other.mkdir()
            with self.assertRaisesRegex(ValueError, "does not match"):
                MODULE._validate_route_screen(screen, other)

    def test_arm_summary_rejects_runtime_protocol_drift(self) -> None:
        arm = {
            "id": "C2_ORDERED_QUEUE",
            "chunk_execution_protocol": "pi05-open-loop-queue-v1",
            "chunk_execution_steps": 10,
        }
        audit = {
            "status": "passed",
            "successes": 2,
            "trials": 3,
            "success_rate": 2 / 3,
            "force_violation_count": 0,
            "expert_fallback_count": 0,
            "vla_qualified_run_count": 3,
            "runs": [
                {
                    "policy": {
                        "chunk_execution_protocol": "first-action-hold-v1",
                        "chunk_execution_steps": 1,
                    }
                }
            ],
        }

        summary = MODULE._summarize_arm(arm, audit)

        self.assertEqual(summary["status"], "failed")
        self.assertIn("chunk_execution_protocol_mismatch", summary["errors"])
        self.assertIn("chunk_execution_steps_mismatch", summary["errors"])


if __name__ == "__main__":
    unittest.main()
