from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_genome_learning_memory import verify_genome_learning_memory


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-genome-learning-memory-v1.json"


class GTMGenomeLearningMemoryArtifactV1Tests(unittest.TestCase):
    def test_production_memory_is_sealed_empty_and_human_gated(self) -> None:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        verify_genome_learning_memory(payload)
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(payload["records"], [])
        self.assertTrue(payload["human_approval_required"])
        self.assertEqual(payload["automatic_promotion_count"], 0)
        self.assertFalse(payload["current_run_mutation_allowed"])


if __name__ == "__main__":
    unittest.main()
