from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compile_keep_unpostable_learning_decision_v1.py"
ROOM = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-execution-room-v1"


class KeepUnpostableLearningDecisionV1Tests(unittest.TestCase):
    def run_compiler(self, observation: dict, directory: Path) -> dict:
        source = directory / "observation.json"
        output = directory / "decision.json"
        source.write_text(json.dumps(observation), encoding="utf-8")
        result = subprocess.run(
            ["python3", "-B", str(SCRIPT), "--observation", str(source), "--output", str(output)],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(output.read_text(encoding="utf-8"))

    def test_empty_template_stays_waiting_without_inventing_effect(self) -> None:
        observation = json.loads((ROOM / "observation-template.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            decision = self.run_compiler(observation, Path(directory))
        self.assertEqual(decision["waiting_route_count"], 2)
        self.assertEqual(decision["human_decision_recorded_route_count"], 0)
        self.assertEqual(decision["automatic_strategy_change_count"], 0)
        self.assertEqual(decision["automatic_memory_promotion_count"], 0)
        self.assertFalse(decision["causal_claim_allowed"])
        self.assertFalse(decision["external_action_executed"])

    def test_complete_observation_computes_descriptive_rates_but_requires_memory_approval(self) -> None:
        row = {
            "provider": "tiktok",
            "release_url": "https://example.test/evidence/tiktok",
            "released_at_utc": "2026-08-04T14:00:00Z",
            "exposures": 1000,
            "qualified_comprehension_actions": 100,
            "qualified_private_starts": 40,
            "day_7_decisions": {"keep": 10, "edit": 4, "export": 2, "delete": 4},
            "continue_opt_ins": 8,
            "misread_as_public_reveal": 2,
            "streak_pressure_objections": 1,
            "owner_decision": "ITERATE",
            "evidence_urls": ["https://example.test/evidence/tiktok"],
        }
        observation = {"campaign_id": "keep-the-unpostable-organic-v1", "rows": [row, {**row, "provider": "instagram", "release_url": "https://example.test/evidence/instagram", "evidence_urls": ["https://example.test/evidence/instagram"]}]}
        with tempfile.TemporaryDirectory() as directory:
            decision = self.run_compiler(observation, Path(directory))
        self.assertEqual(decision["waiting_route_count"], 0)
        self.assertEqual(decision["human_decision_recorded_route_count"], 2)
        tiktok = decision["route_decisions"][0]
        self.assertEqual(tiktok["descriptive_metrics"]["comprehension_per_exposure"], 0.1)
        self.assertEqual(tiktok["descriptive_metrics"]["day_7_decision_per_private_start"], 0.5)
        self.assertFalse(tiktok["automatic_strategy_change"])
        self.assertEqual(tiktok["memory_promotion_state"], "PENDING_SEPARATE_HUMAN_APPROVAL")


if __name__ == "__main__":
    unittest.main()
