import json
import tempfile
import unittest
from pathlib import Path

from autotuner.config import load_config
from autotuner.runner import run_tuning


ROOT = Path(__file__).resolve().parents[1]


class RunnerAndReportTests(unittest.TestCase):
    def test_demo_exports_complete_artifact_set(self) -> None:
        config = load_config(ROOT / "configs" / "demo.json")
        config.trials = 4
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            record = run_tuning(config, output, mock=True)
            self.assertEqual(len(record.trials), 4)
            self.assertTrue(any(not trial.accepted for trial in record.trials))
            self.assertTrue((output / "run.json").exists())
            self.assertTrue((output / "best_preset.json").exists())
            self.assertTrue((output / "engineering_report.md").exists())
            self.assertTrue((output / "dashboard.html").exists())
            payload = json.loads((output / "run.json").read_text())
            self.assertEqual(payload["best_candidate_key"], record.best_candidate_key)
            report = (output / "engineering_report.md").read_text()
            self.assertIn("Simulation only", report)


if __name__ == "__main__":
    unittest.main()
