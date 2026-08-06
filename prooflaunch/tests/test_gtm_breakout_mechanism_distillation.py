from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_breakout_mechanism_distillation import (
    GTMBreakoutMechanismDistillationError,
    compile_breakout_mechanism_distillation,
    verify_breakout_mechanism_distillation,
)
from scripts.compile_gtm_breakout_mechanism_distillation import BLUEPRINTS


class BreakoutMechanismDistillationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = json.loads(Path("evidence/v10/gtm-breakout-quality-team-seed-v1.json").read_text(encoding="utf-8"))

    def test_blueprints_are_bounded_and_source_ready(self):
        payload = compile_breakout_mechanism_distillation(self.seed, BLUEPRINTS, compiled_at="2026-08-04T00:00:00-04:00")
        verify_breakout_mechanism_distillation(payload)
        self.assertEqual(payload["blueprint_count"], 21)
        self.assertFalse(payload["budget_policy"]["zero_budget_is_required"])
        self.assertTrue(all(blueprint["copy_reuse_allowed"] is False for blueprint in payload["blueprints"]))
        self.assertTrue(all(blueprint["automatic_publish_or_spend_allowed"] is False for blueprint in payload["blueprints"]))
        ready = {team["team_id"] for team in self.seed["teams"] if team["promotion_status"] == "mechanism_distillation_ready"}
        self.assertTrue(all(set(blueprint["source_team_ids"]).issubset(ready) for blueprint in payload["blueprints"]))

    def test_outcome_only_source_is_rejected(self):
        invalid = copy.deepcopy(BLUEPRINTS)
        invalid[0]["source_team_ids"] = ["cursor"]
        with self.assertRaises(GTMBreakoutMechanismDistillationError):
            compile_breakout_mechanism_distillation(self.seed, invalid, compiled_at="2026-08-04T00:00:00-04:00")

    def test_tamper_is_rejected(self):
        payload = compile_breakout_mechanism_distillation(self.seed, BLUEPRINTS, compiled_at="2026-08-04T00:00:00-04:00")
        tampered = copy.deepcopy(payload)
        tampered["blueprints"][0]["copy_reuse_allowed"] = True
        with self.assertRaises(GTMBreakoutMechanismDistillationError):
            verify_breakout_mechanism_distillation(tampered)


if __name__ == "__main__":
    unittest.main()
