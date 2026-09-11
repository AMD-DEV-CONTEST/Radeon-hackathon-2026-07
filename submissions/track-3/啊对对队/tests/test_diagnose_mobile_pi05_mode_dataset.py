import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "diagnose_mobile_pi05_mode_dataset.py"
)
SPEC = importlib.util.spec_from_file_location(
    "diagnose_mobile_pi05_mode_dataset", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MobilePI05ModeDatasetDiagnosticTests(unittest.TestCase):
    def test_quantile_normalization_preserves_mode_label(self) -> None:
        stats = {
            "q01": [0.0] * 9 + [-1.0, -1.0, -1.0],
            "q99": [1.0] * 9 + [1.0, 1.0, 1.0],
        }
        action = [0.0] * 9 + [-1.0, 1.0, -1.0]

        mode = MODULE._quantile_normalized_mode(action, stats)

        self.assertEqual(mode, "side_suction")

    def test_detects_channel_specific_quantile_argmax_change(self) -> None:
        stats = {
            "q01": [0.0] * 9 + [-1.0, -3.0, -1.0],
            "q99": [1.0] * 9 + [9.0, -1.0, 1.0],
        }
        action = [0.0] * 9 + [1.0, -1.0, -1.0]

        raw_mode = MODULE._mode(action)
        normalized_mode = MODULE._quantile_normalized_mode(action, stats)

        self.assertEqual(raw_mode, "top_suction")
        self.assertNotEqual(normalized_mode, raw_mode)


if __name__ == "__main__":
    unittest.main()
