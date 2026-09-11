from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.audit_grasp_candidate_model_selection_v2_protocol import audit_protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT_ROOT / "configs/grasp_candidate_model_selection_v2.toml"


class GraspCandidateModelSelectionV2ProtocolTests(unittest.TestCase):
    def test_frozen_protocol_passes(self) -> None:
        result = audit_protocol(PROTOCOL)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["parameter_count"], 6276)
        self.assertTrue(result["holdout_locked"])

    def test_rejects_holdout_unlock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.toml"
            path.write_text(
                PROTOCOL.read_text(encoding="utf-8").replace(
                    "locked = true",
                    "locked = false",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "holdout"):
                audit_protocol(path)


if __name__ == "__main__":
    unittest.main()
