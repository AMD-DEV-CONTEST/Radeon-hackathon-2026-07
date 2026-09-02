import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "capture_rocm_telemetry.py"
SPEC = importlib.util.spec_from_file_location("rocm_capture", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ROCmTelemetryCaptureTests(unittest.TestCase):
    def test_parses_parent_and_rss(self):
        parent, rss = MODULE.parse_process_status("Name:\ttest\nPPid:\t42\nVmRSS:\t2048 kB\n")
        self.assertEqual(parent, 42)
        self.assertEqual(rss, 2 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
