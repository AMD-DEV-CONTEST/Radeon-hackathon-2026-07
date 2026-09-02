import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "run_radeon_failure_matrix.py"
SPEC = importlib.util.spec_from_file_location("run_radeon_failure_matrix", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class RadeonFailureMatrixTests(unittest.TestCase):
    def test_evaluate_requires_safe_fallback_and_visible_fail_closed_results(self) -> None:
        results = {
            "api_loss": {
                "exit_code": 0,
                "result_present": True,
                "runtime_passed": True,
                "contract_passed": True,
                "failure_code": "",
            },
            "model_loss": {
                "exit_code": 0,
                "result_present": True,
                "runtime_passed": False,
                "contract_passed": False,
                "failure_code": "component_failure",
            },
            "retrieval_loss": {
                "exit_code": 1,
                "result_present": False,
                "runtime_passed": None,
                "contract_passed": None,
                "failure_code": "",
            },
        }
        self.assertTrue(all(MODULE.evaluate(results).values()))

    def test_evaluate_rejects_silent_success_or_unsafe_api_loss(self) -> None:
        results = {
            "api_loss": {
                "exit_code": 0,
                "result_present": True,
                "runtime_passed": False,
                "contract_passed": False,
                "failure_code": "timeout",
            },
            "model_loss": {
                "exit_code": 0,
                "result_present": True,
                "runtime_passed": True,
                "contract_passed": True,
                "failure_code": "",
            },
            "retrieval_loss": {
                "exit_code": 0,
                "result_present": False,
                "runtime_passed": None,
                "contract_passed": None,
                "failure_code": "",
            },
        }
        self.assertFalse(any(MODULE.evaluate(results).values()))


if __name__ == "__main__":
    unittest.main()
