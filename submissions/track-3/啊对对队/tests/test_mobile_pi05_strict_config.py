import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_mobile_pi05_strict_config.py"
SPEC = importlib.util.spec_from_file_location("audit_mobile_pi05_strict_config", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _config() -> dict:
    return {
        "episodes": [
            {
                "episode_id": mode,
                "grasp_mode": mode,
                "task_text": "Recover contact and transport the parcel.",
                "recovery_contact_offset_m": [0, 0, 0],
                "recovery_contact_penetration_delta_m": 0,
                "recovery_left_lift_offset_m": [0, 0, 0],
                "recovery_right_lift_offset_m": [0, 0, 0],
            }
            for mode in MODULE.PI05_GRASP_MODES
        ]
    }


class MobilePI05StrictConfigTests(unittest.TestCase):
    def test_accepts_mode_neutral_zero_correction_config(self) -> None:
        result = MODULE.audit_strict_config(_config())

        self.assertEqual(result["status"], "passed")

    def test_rejects_language_and_expert_correction_leakage(self) -> None:
        config = _config()
        config["episodes"][0]["task_text"] = "Use top suction."
        config["episodes"][1]["recovery_contact_offset_m"] = [0.001, 0, 0]

        result = MODULE.audit_strict_config(config)

        self.assertEqual(result["status"], "failed")
        self.assertIn("mode_language_leakage:top_suction", result["errors"])
        self.assertIn(
            "expert_vector_correction:side_suction:recovery_contact_offset_m",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
