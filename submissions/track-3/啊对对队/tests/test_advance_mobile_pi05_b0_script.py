from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "advance_mobile_pi05_b0_after_postscreen_rocm.sh"
)


class AdvanceMobilePI05B0ScriptTests(unittest.TestCase):
    def test_keeps_selection_development_only(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("select_mobile_pi05_route_checkpoint.py", text)
        self.assertIn("run_mobile_pi05_b0_strict_dev_rocm.sh", text)
        self.assertNotIn("heldout", text.lower())
        self.assertNotIn("105", text)


if __name__ == "__main__":
    unittest.main()
