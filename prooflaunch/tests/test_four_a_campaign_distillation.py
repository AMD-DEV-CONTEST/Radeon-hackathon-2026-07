from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.four_a_campaign_distillation import (
    AgencyReference,
    AssertionKind,
    CampaignDistillationCase,
    CampaignSource,
    CorpusPartition,
    FourACampaignDistillationContract,
    LayerAssertion,
    REQUIRED_DISTILLATION_LAYERS,
)


ROOT = Path(__file__).resolve().parents[1]


def source(source_id: str, kind: str = "owned_primary_record") -> CampaignSource:
    return CampaignSource(
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        publisher="Example",
        retrieved_at="2026-07-30",
        locator=f"record:{source_id}",
        snapshot_sha256=hashlib.sha256(source_id.encode()).hexdigest(),
        snapshot_kind=kind,
    )


def layers(*source_ids: str) -> dict[str, LayerAssertion]:
    return {
        name: LayerAssertion(
            text=f"{name} assertion",
            kind=AssertionKind.OBSERVED,
            source_ids=tuple(source_ids),
            confidence=1.0,
        )
        for name in REQUIRED_DISTILLATION_LAYERS
    }


class FourACampaignDistillationTests(unittest.TestCase):
    def test_public_reference_cannot_be_silently_promoted_to_training(self) -> None:
        public = source("public", "metadata_transcription")
        owned = source("owned")
        case = CampaignDistillationCase(
            case_id="case-1",
            agency_id="agency-1",
            title="A",
            brand="B",
            year=2026,
            annual_id="X",
            channels=("video",),
            partition=CorpusPartition.TRAINING_CANDIDATE,
            source_ids=("public", "owned"),
            layers=layers("public", "owned"),
        )
        failures = case.audit({"agency-1"}, {"public": public, "owned": owned})
        self.assertTrue(any("cannot authorize training" in item for item in failures))

    def test_deep_case_requires_all_sixteen_layers_and_source_binding(self) -> None:
        item = source("s1")
        incomplete = layers("s1")
        incomplete.pop("counterfactuals")
        case = CampaignDistillationCase(
            case_id="case-1",
            agency_id="agency-1",
            title="A",
            brand="B",
            year=2026,
            annual_id="X",
            channels=("video",),
            partition=CorpusPartition.RESEARCH_REFERENCE,
            source_ids=("s1", "s2"),
            layers=incomplete,
        )
        failures = case.audit(
            {"agency-1"},
            {"s1": item, "s2": source("s2")},
        )
        self.assertTrue(any("missing layers counterfactuals" in x for x in failures))

    def test_raw_campaign_assets_are_rejected_from_abstraction_record(self) -> None:
        case = CampaignDistillationCase(
            case_id="case-1",
            agency_id="agency-1",
            title="A",
            brand="B",
            year=2026,
            annual_id="X",
            channels=("video",),
            partition=CorpusPartition.RESEARCH_REFERENCE,
            source_ids=("s1", "s2"),
            layers=layers("s1"),
            contains_raw_campaign_asset=True,
        )
        failures = case.audit(
            {"agency-1"},
            {"s1": source("s1"), "s2": source("s2")},
        )
        self.assertTrue(any("raw campaign asset" in x for x in failures))

    def test_contract_rejects_small_or_unbalanced_reference_cohort(self) -> None:
        agencies = (
            AgencyReference("a1", "A1", "New York", "US", 1, 10, "rank"),
        )
        report = FourACampaignDistillationContract().evaluate(
            agencies,
            (source("rank"),),
            (),
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("agency cohort" in x for x in report.failures))
        self.assertTrue(any("campaign case count" in x for x in report.failures))

    def test_generated_manifest_is_content_addressed_and_fail_closed(self) -> None:
        payload = json.loads(
            (
                ROOT / "config" / "north_america_4a_research_cohort_2026.json"
            ).read_text(encoding="utf-8")
        )
        expected = payload.pop("manifest_sha256")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected)
        self.assertEqual(len(payload["agencies"]), 10)
        self.assertEqual(len(payload["distillation_layers"]), 16)
        self.assertEqual(len(payload["acquisition_queue"]["discovery_pages"]), 10)
        self.assertGreaterEqual(
            payload["acquisition_queue"]["observed_unique_candidate_count"],
            35,
        )
        self.assertTrue(
            payload["acquisition_queue"][
                "award_category_rows_are_not_distinct_campaigns"
            ]
        )
        self.assertFalse(payload["admission"]["training"])
        self.assertFalse(payload["admission"]["raw_campaign_assets_stored"])
        fully_distilled_agencies = {
            case["agency_id"]
            for case in payload["seed_cases"]
            if set(case["layers"]) == set(payload["distillation_layers"])
        }
        self.assertEqual(
            fully_distilled_agencies,
            {agency["agency_id"] for agency in payload["agencies"]},
        )
        self.assertGreaterEqual(len(payload["seed_cases"]), 13)
        self.assertTrue(
            all(
                set(case["layers"]) == set(payload["distillation_layers"])
                for case in payload["seed_cases"]
            )
        )


if __name__ == "__main__":
    unittest.main()
