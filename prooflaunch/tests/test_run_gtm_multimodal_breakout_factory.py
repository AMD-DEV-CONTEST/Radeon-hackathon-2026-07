from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_multimodal_breakout_factory import verify_multimodal_breakout_factory


ROOT = Path(__file__).resolve().parents[1]


class RunGTMMultimodalBreakoutFactoryTests(unittest.TestCase):
    def test_arbitrary_owner_brief_compiles_to_sealed_model_ready_factory(self) -> None:
        brief = {
            "brief_id": "arbitrary-b2b-industrial-robotics", "business_model": "b2b", "lifecycle": "pre_pmf",
            "industry": "industrial robotics", "category": "robot fleet observability", "product_surface": "web_agent",
            "platform": "linkedin", "audience": "plant reliability leaders", "decision_job": "choose whether to run a bounded pilot",
            "tension": "automation dashboards hide the failure sequence operators need to trust",
            "approved_proof": "one owner-approved fault replay is available",
            "brand_voice": "technical, calm, field-specific, candid", "budget": "zero",
        }
        with tempfile.TemporaryDirectory() as temp:
            brief_path = Path(temp) / "brief.json"
            output_path = Path(temp) / "factory.json"
            brief_path.write_text(json.dumps(brief), encoding="utf-8")
            result = subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"), "-B", str(ROOT / "scripts/run_gtm_multimodal_breakout_factory.py"),
                    "--brief", str(brief_path), "--output", str(output_path),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
                env={"PYTHONPATH": str(ROOT / "src")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            verify_multimodal_breakout_factory(payload)
            self.assertEqual(payload["brief"]["industry"], "industrial robotics")
            self.assertTrue(payload["zero_budget_mode"])
            self.assertEqual(payload["model_call_budget"]["total"], 9)
            self.assertEqual(len(payload["candidate_campaigns"]), 3)


if __name__ == "__main__":
    unittest.main()
