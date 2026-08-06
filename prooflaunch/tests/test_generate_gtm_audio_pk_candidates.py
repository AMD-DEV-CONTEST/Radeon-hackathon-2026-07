from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/generate_gtm_audio_pk_candidates.py"
SPEC = importlib.util.spec_from_file_location("generate_gtm_audio_pk_candidates", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GTMAudioPKCandidateTests(unittest.TestCase):
    def test_voice_directions_are_distinct_non_imitation_and_same_script(self) -> None:
        self.assertEqual(len(MODULE.VOICE_DIRECTIONS), 3)
        self.assertEqual(
            len({row["candidate_id"] for row in MODULE.VOICE_DIRECTIONS}),
            3,
        )
        self.assertEqual(len({row["seed"] for row in MODULE.VOICE_DIRECTIONS}), 3)
        self.assertTrue(all(row["speed"] == 1.20 for row in MODULE.VOICE_DIRECTIONS))
        combined = " ".join(row["instruct"].lower() for row in MODULE.VOICE_DIRECTIONS)
        for forbidden in ("celebrity", "clone", "imitate", "sound like"):
            self.assertNotIn(forbidden, combined)
        self.assertIn("Inspect the proof", MODULE.SCRIPT)
        self.assertIn("Approve manually", MODULE.SCRIPT)

    def test_seal_is_canonical_and_truth_boundary_blocks_quality_claim(self) -> None:
        payload = {
            "schema": "ProofLaunchGTMAudioPKCandidatesV1",
            "human_preference_observed": False,
            "four_a_quality_proven": False,
        }
        sealed = MODULE._seal(payload)
        expected = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(sealed["content_sha256"], expected)

    def test_validation_rejects_output_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            model = temporary_root / MODULE.MODEL_REVISION
            model.mkdir()
            (model / "model.safetensors").write_bytes(b"weights")
            ffmpeg = temporary_root / "ffmpeg"
            ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
            ffmpeg.chmod(0o700)
            with self.assertRaises(SystemExit):
                MODULE._validate_inputs(model, ffmpeg, temporary_root / "out")


if __name__ == "__main__":
    unittest.main()
