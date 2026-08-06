from __future__ import annotations

import copy
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import (
    ContractError,
    TRAINING_SEED_CLAIM_BOUNDARY,
    TRAINING_SEED_POOL,
    load_json,
    validate_training_seed_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


class TrainingSeedManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(ROOT / "configs/training-seeds-v1.json")
        self.task = load_json(ROOT / "configs/task-pack-v1.json")

    def _rejects(self, manifest, task=None) -> None:
        with self.assertRaises(ContractError):
            validate_training_seed_manifest(manifest, task if task is not None else self.task)

    def test_checked_in_manifest_is_valid(self) -> None:
        validate_training_seed_manifest(self.manifest, self.task)

    def test_sizes_and_deterministic_prefixes(self) -> None:
        pool = list(range(1001, 1051))
        self.assertEqual(TRAINING_SEED_POOL, pool)
        seed_sets = self.manifest["seed_sets"]
        self.assertEqual(seed_sets["portability_smoke"], pool[:3])
        self.assertEqual(seed_sets["initial_capture"], pool[:10])
        self.assertEqual(seed_sets["expansion_capture"], pool)
        self.assertEqual(len(seed_sets["portability_smoke"]), 3)
        self.assertEqual(len(seed_sets["initial_capture"]), 10)
        self.assertEqual(len(seed_sets["expansion_capture"]), 50)

    def test_seed_sets_are_nested(self) -> None:
        seed_sets = self.manifest["seed_sets"]
        smoke = set(seed_sets["portability_smoke"])
        initial = set(seed_sets["initial_capture"])
        expansion = set(seed_sets["expansion_capture"])
        self.assertTrue(smoke <= initial <= expansion)

    def test_checked_in_manifest_is_disjoint_from_all_eval_seeds(self) -> None:
        eval_seeds = set()
        for seeds in self.task["evaluation"]["seed_sets"].values():
            eval_seeds.update(seeds)
        manifest_seeds = set(self.manifest["seed_sets"]["expansion_capture"])
        self.assertFalse(eval_seeds & manifest_seeds)

    def test_scalar_field_drift_is_rejected(self) -> None:
        # Each contract-bearing scalar is pinned by exact equality.
        drifts = {
            "manifest_version": "training-seeds-v2",
            "status": "allocation_complete",
            "seed_pool_range": [1001, 1049],
            "allocation_rule": "arbitrary pool; sizes may vary",
            "disjointness": "seeds may overlap evaluation seeds",
        }
        for field, value in drifts.items():
            broken = copy.deepcopy(self.manifest)
            broken[field] = value
            with self.subTest(field=field):
                self._rejects(broken)

    def test_seed_drift_classes_are_rejected(self) -> None:
        cases = {
            "duplicate": [1001, 1001, 1002],
            "unsorted": [1003, 1001, 1002],
            "nonpositive": [0, 1002, 1003],
            "wrong_size": [1001, 1002],
            "non_deterministic": [1099, 1100, 1101],
        }
        for label, seeds in cases.items():
            broken = copy.deepcopy(self.manifest)
            broken["seed_sets"]["portability_smoke"] = seeds
            with self.subTest(label=label):
                self._rejects(broken)

    def test_protocol_linkage_drift_is_rejected(self) -> None:
        cases = {
            "task_id": "different_task",
            "protocol_version": "different_protocol",
            "source_compatibility_protocol": "different_protocol",
            "protocol_comparability": "directly_comparable",
        }
        for field, value in cases.items():
            broken = copy.deepcopy(self.manifest)
            broken[field] = value
            with self.subTest(field=field):
                self._rejects(broken)

    def test_eval_leakage_is_rejected(self) -> None:
        # g1 is checked as an explicit extra safety condition.
        g1_task = copy.deepcopy(self.task)
        g1_task["evaluation"]["seed_sets"]["g1_smoke"] = [1001]
        self._rejects(self.manifest, g1_task)

        gate_task = copy.deepcopy(self.task)
        gate_task["evaluation"]["seed_sets"]["g2_early"].append(1042)
        self._rejects(self.manifest, gate_task)

    def test_claim_boundary_phrase_removal_is_rejected(self) -> None:
        # Each no-claim phrase and the no-run/capture/export/train sentence must
        # remain present; exact equality makes any removal fail.  These also pin
        # that the phrase is part of the frozen boundary.
        phrases = {
            "task_success": "task success",
            "multi_seed_robustness": "multi-seed robustness",
            "amd_rocm": "AMD/ROCm",
            "learned_policy": "learned-policy",
            "collection": "episode collection",
            "no_run_sentence": (
                "No episode has been run, captured, exported, or trained against these seeds."
            ),
        }
        for label, phrase in phrases.items():
            self.assertIn(phrase, TRAINING_SEED_CLAIM_BOUNDARY)
            broken = copy.deepcopy(self.manifest)
            broken["claim_boundary"] = TRAINING_SEED_CLAIM_BOUNDARY.replace(phrase, "")
            with self.subTest(label=label):
                self._rejects(broken)

    def test_claim_boundary_replacement_is_rejected(self) -> None:
        broken = copy.deepcopy(self.manifest)
        broken["claim_boundary"] = "training is complete and successful"
        self._rejects(broken)


if __name__ == "__main__":
    unittest.main()
