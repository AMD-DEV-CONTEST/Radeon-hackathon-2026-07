from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_causal_twin_training import (
    CONFOUNDERS,
    MARKETS,
    PRODUCT_KINDS,
    evaluate_estimators,
    generate_causal_time_series,
    hierarchical_cold_start_transfer,
)
from prooflaunch_remix.v10_contracts import EvidenceClass, V10ContractError


ROOT = Path(__file__).resolve().parents[1]


class CausalTwinTimeSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = generate_causal_time_series()
        cls.train = tuple(row for row in cls.rows if row.split == "train")
        cls.validation = tuple(row for row in cls.rows if row.split == "validation")
        cls.test = tuple(row for row in cls.rows if row.split == "test")

    def test_corpus_is_exact_rights_bound_two_product_strict_temporal_holdout(self) -> None:
        self.assertEqual(len(self.rows), 1_200)
        self.assertEqual({row.product_kind for row in self.rows}, set(PRODUCT_KINDS))
        self.assertEqual({row.market for row in self.rows}, set(MARKETS))
        self.assertEqual((len(self.train), len(self.validation), len(self.test)), (800, 200, 200))
        self.assertLess(max(row.day_index for row in self.train), min(row.day_index for row in self.validation))
        self.assertLess(max(row.day_index for row in self.validation), min(row.day_index for row in self.test))
        self.assertTrue((ROOT / "LICENSE").is_file())
        self.assertTrue(all(row.license_locator == "project://LICENSE" for row in self.rows))
        self.assertTrue(all(row.evidence_class == EvidenceClass.SIMULATED for row in self.rows))

    def test_five_confounders_source_rows_and_manifest_are_hash_bound(self) -> None:
        manifest_path = ROOT / "data/v10_causal_twin_timeseries/manifest.json"
        rows_path = ROOT / "data/v10_causal_twin_timeseries/rows.jsonl"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["confounders"], list(CONFOUNDERS))
        self.assertEqual(manifest["rights"]["external_training_material_count"], 0)
        self.assertEqual(
            manifest["artifacts"]["rows"]["sha256"],
            hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        )
        unique_counts = {name: len({getattr(row, name) for row in self.rows}) for name in CONFOUNDERS}
        self.assertTrue(all(count > 20 for count in unique_counts.values()), unique_counts)
        self.assertEqual({row.treated for row in self.rows}, {False, True})
        self.assertGreater(len({row.outcome for row in self.rows}), 1_000)

    def test_naive_ipw_and_doubly_robust_controls_use_sealed_time_and_known_truth(self) -> None:
        report = evaluate_estimators(self.train, self.test)
        self.assertEqual(
            report.method_order,
            ("naive_correlation", "estimated_propensity_ipw", "aipw_doubly_robust"),
        )
        self.assertLess(report.doubly_robust_absolute_error, report.naive_absolute_error)
        self.assertGreater(report.ipw_absolute_error, report.doubly_robust_absolute_error)
        self.assertGreater(report.propensity_minimum, 0.02)
        self.assertLess(report.propensity_maximum, 0.98)
        self.assertFalse(report.real_business_effect_claim_allowed)
        with self.assertRaises(V10ContractError):
            evaluate_estimators(self.validation, self.train)

    def test_hierarchical_cold_start_uses_train_only_and_zero_target_observations(self) -> None:
        target = {name: 0.0 for name in CONFOUNDERS}
        first = hierarchical_cold_start_transfer(
            self.train, target_product_kind="ai_agent", target_profile=target
        )
        second = hierarchical_cold_start_transfer(
            self.train, target_product_kind="ai_agent", target_profile=target
        )
        self.assertEqual(first, second)
        self.assertEqual(first.target_market_observation_count, 0)
        self.assertEqual(first.source_market_count, 2)
        self.assertEqual(len(first.nearest_markets), 2)
        self.assertFalse(first.real_business_effect_claim_allowed)
        with self.assertRaises(V10ContractError):
            hierarchical_cold_start_transfer(
                (*self.train, self.validation[0]),
                target_product_kind="ai_agent",
                target_profile=target,
            )


if __name__ == "__main__":
    unittest.main()
