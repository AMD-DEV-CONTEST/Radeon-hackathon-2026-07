from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from prooflaunch_remix.v10_curated_human_audit import (
    ATTESTATION,
    AUDIT_CASE_COUNT,
    AUDIT_STRATA,
    EXPECTED_REVIEW_COUNT,
    RUBRIC_DIMENSIONS,
    aggregate_completed_reviews,
    review_digest,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CuratedHumanAuditTests(unittest.TestCase):
    def test_packet_is_exactly_1500_stratified_cases_and_4500_blank_human_assignments(self) -> None:
        root = ROOT / "data/v10_curated_human_audit"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        cases = _read(root / "blind-cases.jsonl")
        assignments = _read(root / "assignments.jsonl")
        self.assertEqual(manifest["case_count"], AUDIT_CASE_COUNT)
        self.assertEqual(manifest["strata"], AUDIT_STRATA)
        self.assertEqual(Counter(row["stratum"] for row in cases), Counter(AUDIT_STRATA))
        self.assertEqual(len({row["case_id"] for row in cases}), AUDIT_CASE_COUNT)
        self.assertEqual(len(assignments), EXPECTED_REVIEW_COUNT)
        self.assertFalse(any(row["source_provider_names_exposed"] for row in cases))
        self.assertFalse(any(row["source_urls_exposed"] for row in cases))
        self.assertNotIn("https://", json.dumps(cases).lower())
        self.assertNotIn("http://", json.dumps(cases).lower())
        for slot in range(1, 4):
            templates = _read(root / f"review-templates/reviewer-{slot:02d}.jsonl")
            self.assertEqual(len(templates), AUDIT_CASE_COUNT)
            self.assertTrue(all(set(row["scores"]) == set(RUBRIC_DIMENSIONS) for row in templates))
            self.assertTrue(all(all(value is None for value in row["scores"].values()) for row in templates))
        self.assertEqual(manifest["human_reviews_observed"], 0)
        self.assertFalse(manifest["freeze_passed"])

    def test_distributions_and_visual_assets_bind_all_selected_records(self) -> None:
        root = ROOT / "data/v10_curated_human_audit"
        provenance = _read(root / "selection-provenance.jsonl")
        distribution = json.loads((root / "distributions.json").read_text(encoding="utf-8"))
        long_tail = json.loads((root / "concept-long-tail.json").read_text(encoding="utf-8"))
        source_distribution = json.loads((root / "source-distribution.json").read_text(encoding="utf-8"))
        self.assertEqual(len(provenance), AUDIT_CASE_COUNT)
        for dimension in ("stratum", "provider", "license", "modality", "stage", "content_class"):
            self.assertEqual(distribution["dimension_totals"][dimension], AUDIT_CASE_COUNT)
        self.assertGreaterEqual(distribution["dimension_totals"]["concept"], AUDIT_CASE_COUNT)
        frequencies = [row["count"] for row in long_tail["concepts_ascending_frequency"]]
        self.assertEqual(frequencies, sorted(frequencies))
        self.assertEqual(source_distribution["provider_count_total"], AUDIT_CASE_COUNT)
        self.assertEqual(source_distribution["license_count_total"], AUDIT_CASE_COUNT)
        visual_rows = [row for row in provenance if row["stratum"] == "region"]
        self.assertEqual(len(visual_rows), AUDIT_STRATA["region"])
        for row in visual_rows:
            asset = root / "assets" / f"{row['case_id']}.img"
            self.assertEqual(_sha256_file(asset), row["asset_sha256"])

    def test_zero_human_reviews_cannot_claim_agreement_routing_or_freeze(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/curated-1500-human-audit-gate.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["status"], "not_observed_incomplete_human_audit")
        self.assertEqual(report["submitted_review_count"], 0)
        self.assertIsNone(report["krippendorff_alpha_ordinal"])
        self.assertIsNone(report["positive_mean_quality"])
        self.assertFalse(report["routing_observed"])
        self.assertFalse(report["agreement_claim_allowed"])
        self.assertFalse(report["positive_mean_4_7_claim_allowed"])
        self.assertFalse(report["curated_corpus_v2_freeze_claim_allowed"])
        self.assertEqual(report["model_generated_review_count"], 0)
        self.assertEqual(report["official_api_generated_review_count"], 0)

    def test_complete_attested_fixture_computes_alpha_and_all_four_routes(self) -> None:
        cases = [
            {
                "case_id": f"case-{index:04d}",
                "case_sha256": hashlib.sha256(f"case-{index}".encode()).hexdigest(),
                "stratum": "sft",
            }
            for index in range(AUDIT_CASE_COUNT)
        ]
        reviews = []
        for index, case in enumerate(cases):
            quality, difficulty = ((5, 2), (2, 2), (4, 3), (4, 5))[index % 4]
            for slot in range(1, 4):
                scores = {dimension: 5 for dimension in RUBRIC_DIMENSIONS}
                scores["overall_quality"] = quality
                scores["difficulty"] = difficulty
                row = {
                    "reviewer_slot": slot,
                    "reviewer_pseudonym": f"human-{slot}",
                    "reviewer_attestation": ATTESTATION,
                    "reviewed_at": "2026-08-01T12:00:00Z",
                    "case_id": case["case_id"],
                    "case_sha256": case["case_sha256"],
                    "scores": scores,
                    "strengths": "The visible payload supports a deterministic quality judgment.",
                    "required_rework": "none" if min(scores.values()) == 5 else "Address the scored weakness before promotion.",
                    "recommended_route": "repair",
                    "review_content_sha256": None,
                }
                row["review_content_sha256"] = review_digest(row)
                reviews.append(row)
        result = aggregate_completed_reviews(cases, reviews)
        self.assertTrue(result["review_set_complete"])
        self.assertEqual(result["krippendorff_alpha_ordinal"], 1.0)
        self.assertTrue(result["alpha_passed"])
        self.assertEqual(result["positive_mean_quality"], 5.0)
        self.assertTrue(result["positive_mean_passed"])
        self.assertEqual(result["route_counts"], {"positive": 375, "remove": 375, "repair": 375, "replay": 375})
        self.assertTrue(result["freeze_passed"])


if __name__ == "__main__":
    unittest.main()
