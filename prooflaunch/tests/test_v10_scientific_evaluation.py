from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_scientific_evaluation import (
    BenchmarkPartition,
    BinaryConfusion,
    BlindPreferenceReceipt,
    MetricReceipt,
    ReviewerCalibrationPlan,
    SCIENTIFIC_METRIC_NAMES,
    build_metric_bundle,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_gtm_bench"
FORMULA = ROOT / "evidence/v10/scientific-metric-formula-fixture.json"
CONTRACT = ROOT / "config/cortex_x_v10_scientific_evaluation_contract.json"


class FrozenBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        cls.cases = [json.loads(line) for line in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_gtm_bench_and_all_nine_partitions_are_content_addressed_and_training_excluded(self) -> None:
        self.assertEqual(self.manifest["case_count"], 18)
        self.assertEqual(set(self.manifest["partition_counts"]), {item.value for item in BenchmarkPartition})
        self.assertTrue(all(count == 2 for count in self.manifest["partition_counts"].values()))
        self.assertEqual(sha256_file(DATA / "cases.jsonl"), self.manifest["case_file_sha256"])
        self.assertEqual(len(set(self.manifest["canaries"].values())), 9)
        self.assertTrue(all(case["split"] == "sealed_test" and case["training_allowed"] is False and case["rights"] == "project_owned" for case in self.cases))
        self.assertTrue(all(stable_sha256(case["payload"]) == case["source_sha256"] for case in self.cases))

    def test_sealed_canaries_do_not_appear_in_non_benchmark_data(self) -> None:
        canaries = tuple(self.manifest["canaries"].values())
        findings = []
        for path in (ROOT / "data").rglob("*"):
            if not path.is_file() or DATA in path.parents or path.suffix.lower() not in {".json", ".jsonl", ".txt", ".md"}:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            if any(canary in content for canary in canaries):
                findings.append(str(path.relative_to(ROOT)))
        self.assertEqual(findings, [])

    def test_image_video_and_gtm_agent_baselines_are_pinned_before_results(self) -> None:
        baseline_set = self.contract["baseline_set"]
        self.assertEqual(baseline_set["execution_status"], "not_run")
        self.assertTrue(baseline_set["selected_before_results"])
        baselines = baseline_set["baselines"]
        self.assertEqual({item["lane"] for item in baselines}, {"image", "video", "gtm_agent"})
        self.assertTrue(all(len(item["revision"]) == 40 for item in baselines))
        self.assertTrue(all(len(item["settings_sha256"]) == 64 for item in baselines))
        self.assertTrue(all(item["same_input_required"] and item["same_hardware_required"] and item["frozen_before_candidate_results"] for item in baselines))

    def test_audio_partition_contains_real_hash_bound_pcm_wav_fixtures(self) -> None:
        audio = [item for item in self.cases if item["partition"] == "audio"]
        self.assertEqual(len(audio), 2)
        for item in audio:
            path = ROOT / item["payload"]["audio_locator"]
            self.assertGreater(path.stat().st_size, 32_000)
            self.assertEqual(sha256_file(path), item["payload"]["audio_sha256"])


class ScientificMetricTests(unittest.TestCase):
    def test_claim_precision_and_recall_keep_distinct_denominators(self) -> None:
        confusion = BinaryConfusion(8, 2, 4, 6)
        self.assertEqual(confusion.precision_receipt("claim_precision").value, 0.8)
        self.assertEqual(confusion.recall_receipt("claim_recall").value, 8 / 12)

    def test_all_thirteen_metrics_require_raw_possible_counts_in_preregistered_order(self) -> None:
        counts = {name: (9, 10) for name in SCIENTIFIC_METRIC_NAMES[2:]}
        bundle = build_metric_bundle(claim_confusion=BinaryConfusion(9, 1, 1, 9), counts=counts)
        self.assertEqual(tuple(item.metric for item in bundle.metrics), SCIENTIFIC_METRIC_NAMES)
        self.assertTrue(all(item.denominator == 10 for item in bundle.metrics))
        with self.assertRaisesRegex(V10ContractError, "all non-Claim"):
            build_metric_bundle(claim_confusion=BinaryConfusion(1, 0, 0, 1), counts={})

    def test_zero_denominator_and_impossible_counts_fail_closed(self) -> None:
        for numerator, denominator in ((0, 0), (2, 1), (-1, 1)):
            with self.subTest(counts=(numerator, denominator)):
                with self.assertRaises(V10ContractError):
                    MetricReceipt("metric", numerator, denominator, "n/d")

    def test_formula_fixture_is_explicitly_not_model_performance(self) -> None:
        report = json.loads(FORMULA.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual([item["metric"] for item in report["metrics"]], list(SCIENTIFIC_METRIC_NAMES))
        self.assertIn("not system performance", report["truth_boundary"])

    def test_wilson_is_derived_from_raw_blind_counts_not_supplied_score(self) -> None:
        receipt = BlindPreferenceReceipt(120, 150)
        self.assertEqual(receipt.rate, 0.8)
        self.assertGreater(receipt.wilson_lower_95, 0.70)
        with self.assertRaises(V10ContractError):
            BlindPreferenceReceipt(151, 150)

    def test_reviewer_plan_preregisters_five_times_300_but_claims_no_ratings(self) -> None:
        plan = ReviewerCalibrationPlan(("a", "b", "c", "d", "e"), 300, 20, True, True, True)
        self.assertEqual(plan.planned_rating_count, 1500)
        planned = json.loads((ROOT / "evidence/v10/scientific-report.planned.json").read_text(encoding="utf-8"))
        self.assertIsNone(planned["human_evidence"]["rating_count"])
        self.assertFalse(planned["top3_claim_eligible"])
        self.assertFalse(planned["frozen"])


if __name__ == "__main__":
    unittest.main()
