from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GTMKillListExperienceTests(unittest.TestCase):
    def test_experience_is_local_concentrated_and_truth_safe(self) -> None:
        output = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-kill-list-experience-v1"
        receipt = json.loads((output / "gtm-kill-list-receipt.json").read_text(encoding="utf-8"))
        page = (output / "index.html").read_text(encoding="utf-8")
        self.assertEqual(receipt["creative_concept"], "The GTM Kill List")
        self.assertEqual(receipt["channel_count"], 13)
        self.assertEqual(receipt["selected_channel_count"], 3)
        self.assertEqual(receipt["killed_channel_count"], 10)
        self.assertEqual(receipt["network_call_count"], 0)
        self.assertEqual(receipt["model_call_count"], 0)
        self.assertFalse(receipt["external_publish_executed"])
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["production_effect_observed"])
        self.assertIn("KILL 10 CHANNELS", page)
        self.assertNotIn("fetch(", page)
        self.assertNotIn("XMLHttpRequest", page)

    def test_engine_differentiates_six_real_scenario_shapes(self) -> None:
        module = "./artifacts/gtm-last-mile-pk-v1/gtm-kill-list-experience-v1/gtm-kill-list-engine.mjs"
        program = f"""import {{ buildKillList }} from '{module}';
const fixtures = [
  {{businessModel:'b2b',stage:'pre_pmf',budget:'zero',proof:'weak',category:'saas'}},
  {{businessModel:'b2b',stage:'launch',budget:'zero',proof:'working',category:'saas'}},
  {{businessModel:'b2b',stage:'growth',budget:'small',proof:'strong',category:'service'}},
  {{businessModel:'b2c',stage:'pre_pmf',budget:'zero',proof:'weak',category:'consumer_app'}},
  {{businessModel:'b2c',stage:'launch',budget:'small',proof:'working',category:'commerce'}},
  {{businessModel:'b2c',stage:'growth',budget:'scaled',proof:'strong',category:'consumer_app'}}
];
const signatures = new Set();
for (const input of fixtures) {{
  const out=buildKillList(input);
  if(out.selected.length!==3 || out.killed.length!==10) process.exit(1);
  if(out.selected.reduce((n,row)=>n+row.allocation,0)!==100) process.exit(2);
  if(new Set([...out.selected,...out.killed].map(row=>row.id)).size!==13) process.exit(3);
  if([...out.selected,...out.killed].some(row=>!Number.isFinite(row.score))) process.exit(5);
  signatures.add(out.selected.map(row=>row.id).join(':'));
}}
if(signatures.size < 4) process.exit(4);
"""
        result = subprocess.run(["node", "--input-type=module", "-e", program], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
