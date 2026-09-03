from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = (
    ROOT
    / ".ops/wip/g3-targeted-right-first-coverage-20260728"
    / "run_targeted_right_first_collection_20260728_v3.py"
)
SUPERVISOR = (
    ROOT
    / ".ops/wip/g3-targeted-right-first-coverage-20260728"
    / "run_targeted_right_first_supervisor_20260728_v3.sh"
)
SPEC = importlib.util.spec_from_file_location("right_first_v3", RUNNER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TargetedRightFirstCollectionV3Tests(unittest.TestCase):
    def test_exact_seed_derivation_and_rll_patterns(self) -> None:
        candidates, patterns = MODULE.derive_candidates()
        self.assertEqual(candidates, MODULE.CANDIDATES)
        self.assertEqual(len(candidates), 16)
        self.assertTrue(
            all(patterns[seed] == ["right", "left", "left"] for seed in candidates)
        )

    def test_candidates_are_unique_sorted_and_holdout_disjoint(self) -> None:
        task = json.loads((ROOT / "configs/task-pack-v1.json").read_text())
        holdouts = MODULE.evaluation_seeds(task)
        self.assertEqual(MODULE.CANDIDATES, sorted(set(MODULE.CANDIDATES)))
        self.assertFalse(set(MODULE.CANDIDATES) & holdouts)
        self.assertFalse(set(MODULE.CANDIDATES) & MODULE.PREVIOUSLY_ATTEMPTED)

    def test_contract_matches_implementation_constants(self) -> None:
        contract = MODULE.validate_contract(
            ROOT / "configs/targeted-right-first-coverage-v3.json"
        )
        selection = contract["single_intervention"]["seed_selection"]
        self.assertEqual(selection["candidate_seeds"], MODULE.CANDIDATES)
        self.assertEqual(selection["target_pattern"], MODULE.TARGET_PATTERN)

    def test_transform_changes_only_declared_identity_and_guard_strings(self) -> None:
        source = "\n".join(
            [
                f'ROOT = "{MODULE.OLD_ROOT}"',
                f'TOKEN1 = "{MODULE.OLD_TOKEN}"',
                f'TOKEN2 = "{MODULE.OLD_TOKEN}"',
                MODULE.OLD_SEEDS,
                'if g0["count"] != 0:',
                "    pass",
                'if o["count"] != 0:',
                "    pass",
                'if o["count"] != 0:',
                "    pass",
                'if o["count"] != 0:',
                "    pass",
                'capped_aborted = o["count"] != 0',
            ]
        )
        transformed = MODULE.transform_source_text(source)
        self.assertIn(str(MODULE.BATCH), transformed)
        self.assertIn(MODULE.NEW_TOKEN, transformed)
        self.assertIn(MODULE.NEW_SEEDS, transformed)
        self.assertEqual(transformed.count('if not o["available"]:'), 3)
        self.assertNotIn(MODULE.OLD_ROOT, transformed)
        self.assertNotIn(MODULE.OLD_SEEDS, transformed)

    def test_transform_rejects_source_drift(self) -> None:
        with self.assertRaises(RuntimeError):
            MODULE.transform_source_text("SEEDS = []\n")

    def test_terminal_taxonomy(self) -> None:
        self.assertEqual(
            MODULE.classify_terminal(True, True),
            "COMPLETE_RIGHT_FIRST_COVERAGE_ACCEPTED",
        )
        self.assertEqual(
            MODULE.classify_terminal(True, False),
            "COMPLETE_INSUFFICIENT_RIGHT_FIRST_COVERAGE",
        )
        self.assertEqual(
            MODULE.classify_terminal(False, True), "FAILED_EVIDENCE_GATE"
        )

    def test_parent_success_with_independent_audit_failure_is_not_clean(self) -> None:
        self.assertTrue(
            MODULE.successful_record_evidence_clean(
                [{"source_driver_seed_ok": False}]
            )
        )
        self.assertFalse(
            MODULE.successful_record_evidence_clean(
                [{"source_driver_seed_ok": True}]
            )
        )

    def test_write_exclusive_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.txt"
            MODULE.write_exclusive(path, "first\n")
            with self.assertRaises(FileExistsError):
                MODULE.write_exclusive(path, "second\n")
            self.assertEqual(path.read_text(), "first\n")

    def test_verify_item_checks_all_four_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "npz": root / "episode.npz",
                "stage_trace": root / "stage_trace.json",
                "receipt": root / "receipt.json",
                "capture_manifest": root / "capture_manifest.json",
            }
            for label, path in files.items():
                path.write_text(label)
            item = {
                "npz_path": str(files["npz"]),
                "stage_trace_path": str(files["stage_trace"]),
                "receipt_path": str(files["receipt"]),
                "capture_manifest_path": str(files["capture_manifest"]),
                **{
                    f"{label}_sha256": MODULE.sha256_file(path)
                    for label, path in files.items()
                },
            }
            self.assertTrue(MODULE.verify_item(item))
            files["receipt"].write_text("changed")
            self.assertFalse(MODULE.verify_item(item))

    def test_trace_pattern_rejects_non_rll(self) -> None:
        stages = [
            "place_base_bowl_at_target",
            "grasp_and_place_middle_bowl",
            "grasp_and_place_top_bowl",
        ]
        trace = {
            "events": [
                {
                    "stage": stage,
                    "status": "completed",
                    "details": {"assigned_side": side},
                }
                for stage, side in zip(stages, ["right", "left", "left"])
            ]
        }
        self.assertEqual(MODULE.trace_pattern(trace), MODULE.TARGET_PATTERN)
        trace["events"][0]["details"]["assigned_side"] = "left"
        self.assertNotEqual(MODULE.trace_pattern(trace), MODULE.TARGET_PATTERN)

    def test_supervisor_static_isolation_and_no_clobber_guards(self) -> None:
        text = SUPERVISOR.read_text()
        self.assertIn("set -o noclobber", text)
        self.assertIn('CUDA_VISIBLE_DEVICES=""', text)
        self.assertIn("PACKAGE.SHA256SUMS", text)
        self.assertIn("supervisor_final_evidence.SHA256SUMS", text)
        self.assertNotIn("rm -", text)
        self.assertNotIn("kill ", text)


if __name__ == "__main__":
    unittest.main()
