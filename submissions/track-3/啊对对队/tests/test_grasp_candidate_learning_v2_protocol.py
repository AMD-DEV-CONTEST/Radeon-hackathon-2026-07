from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_grasp_candidate_learning_v2_protocol import audit_protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT_ROOT / "configs/grasp_candidate_learning_v2.toml"
SELECTION = (
    PROJECT_ROOT
    / "evidence/training/grasp-candidate-learning-v2-episode-selection.json"
)
CONFIG = PROJECT_ROOT / "configs/catalog_v2.toml"


class GraspCandidateLearningV2ProtocolTests(unittest.TestCase):
    def test_frozen_artifacts_pass_audit(self) -> None:
        result = audit_protocol(PROTOCOL, SELECTION, CONFIG)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["split_counts"],
            {"train": 32, "development": 16, "holdout": 16},
        )
        self.assertTrue(result["holdout_locked"])

    def test_rejects_tampered_selection_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            payload = json.loads(SELECTION.read_text(encoding="utf-8"))
            payload["assignments"][0]["episode"] += 1
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "evidence SHA-256"):
                audit_protocol(PROTOCOL, path, CONFIG)

    def test_rejects_unlocked_holdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.toml"
            path.write_text(
                PROTOCOL.read_text(encoding="utf-8").replace(
                    "holdout_locked = true",
                    "holdout_locked = false",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "holdout must remain locked"):
                audit_protocol(path, SELECTION, CONFIG)


if __name__ == "__main__":
    unittest.main()
