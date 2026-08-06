from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_final_lock import LOCK_PATH, build_lock_bundle, verify_lock_bundle


ROOT = Path(__file__).resolve().parents[1]


class FinalLockTests(unittest.TestCase):
    def test_source_lock_covers_code_tests_web_notebooks_docs_config_and_submission_gate(self) -> None:
        bundle = build_lock_bundle(ROOT)
        paths = {item["path"] for item in bundle["source_lock"]["files"]}
        required = {
            "LICENSE",
            "src/prooflaunch_remix/v10_final_lock.py",
            "scripts/build_v10_final_locks.py",
            "tests/test_v10_final_lock.py",
            "web/index.html",
            "notebooks/prooflaunch_cortex_x_v10_radeon.ipynb",
            "docs/ARCHITECTURE_V10.md",
            "README.md",
            "JUDGE_START_HERE.md",
            "demos/run_track1_demo.py",
            "submission/track1-prooflaunch/README.md",
            "submission/track1-prooflaunch/PR_BODY.md",
            "submission/track1-prooflaunch/RADEON_FINAL_CAPTURE.md",
            "submission/track1-prooflaunch/SUBMISSION_MANIFEST.json",
            "SUBMISSION_GATE.json",
        }
        self.assertTrue(required <= paths)
        self.assertNotIn(LOCK_PATH.as_posix(), paths)

    def test_model_lock_pins_revisions_and_fails_closed_on_unresolved_teacher(self) -> None:
        bundle = build_lock_bundle(ROOT)
        identities = bundle["model_lock"]["identities"]
        admitted = [item for item in identities if item["admitted"]]
        self.assertGreaterEqual(len(admitted), 8)
        self.assertTrue(all(len(item["revision"]) == 40 for item in admitted))
        unresolved = [item for item in identities if not item["admitted"]]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["role"], "distillation_teacher")
        self.assertFalse(bundle["model_lock"]["unresolved_models_admitted"])

    def test_data_lock_hashes_all_publishable_project_data_and_excludes_private_teacher_rows(self) -> None:
        bundle = build_lock_bundle(ROOT)
        paths = {item["path"] for item in bundle["data_lock"]["files"]}
        self.assertIn("data/v10_gtm_seed/manifest.json", paths)
        self.assertIn("data/v10_gtm_bench/manifest.json", paths)
        self.assertFalse(any(path.startswith("data/tokenfactory_teacher_v10/") for path in paths))
        external = bundle["data_lock"]["external_datasets"][0]
        self.assertEqual(external["dataset_id"], "AI-ModelScope/emotion")
        self.assertFalse(external["admitted_for_final_training"])

    def test_generated_lock_matches_current_tree_and_detects_any_section_tamper(self) -> None:
        path = ROOT / LOCK_PATH
        self.assertTrue(path.is_file(), "run scripts/build_v10_final_locks.py")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(verify_lock_bundle(ROOT, bundle), ())
        tampered = copy.deepcopy(bundle)
        tampered["source_lock"]["files"][0]["sha256"] = "0" * 64
        errors = verify_lock_bundle(ROOT, tampered)
        self.assertIn("bundle_digest_mismatch", errors)
        self.assertIn("source_lock_drift", errors)


if __name__ == "__main__":
    unittest.main()
