from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_cpt_corpus import (
    TARGET_CPT_TOKENS,
    CPTCorpusRecord,
    text_sha256,
    verify_cpt_summary,
)


ROOT = Path(__file__).resolve().parents[1]


def record(**overrides: object) -> CPTCorpusRecord:
    text = str(overrides.pop("text", "licensed source text"))
    values: dict[str, object] = {
        "record_id": "cpt-00000001",
        "provider": "verified-provider",
        "source_id": "github:example/project",
        "source_path": "src/module.py",
        "source_revision": "a" * 40,
        "license_spdx": "MIT",
        "license_evidence_url": "https://github.com/example/project/blob/" + "a" * 40 + "/LICENSE",
        "permitted_use": "training_candidate",
        "asset_level_rights_verified": True,
        "commercial_training_allowed": True,
        "rights_basis": "immutable root license plus source-only path audit",
        "content_class": "source_code",
        "text": text,
        "token_count": 3,
        "content_sha256": text_sha256(text),
    }
    values.update(overrides)
    return CPTCorpusRecord(**values)  # type: ignore[arg-type]


class CPTCorpusRightsTests(unittest.TestCase):
    def test_training_record_requires_asset_level_rights(self) -> None:
        self.assertTrue(record().asset_level_rights_verified)
        with self.assertRaises(V10ContractError):
            record(asset_level_rights_verified=False)
        with self.assertRaises(V10ContractError):
            record(commercial_training_allowed=False)

    def test_method_only_and_model_output_records_fail_closed(self) -> None:
        with self.assertRaises(V10ContractError):
            record(permitted_use="method_only")
        with self.assertRaises(V10ContractError):
            record(model_output=True)

    def test_license_name_without_rights_review_is_not_enough(self) -> None:
        with self.assertRaises(V10ContractError):
            record(
                license_spdx="Apache-2.0",
                asset_level_rights_verified=False,
                rights_basis="repository license flag only",
            )

    def test_summary_rejects_any_evaluation_class_tokens(self) -> None:
        summary = {
            "token_count": TARGET_CPT_TOKENS,
            "token_count_observed": True,
            "provider_count": 10,
            "maximum_provider_share": 0.1,
            "duplicate_record_count": 0,
            "near_duplicate_record_count": 0,
            "unresolved_rights_count": 0,
            "model_output_record_count": 0,
            "evaluation_contamination_count": 0,
            "forbidden_evaluation_class_token_count": 1,
            "tokenizer_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "corpus_content_sha256": "c" * 64,
            "provider_token_counts": {f"p-{index}": 1_500_000 for index in range(10)},
        }
        with self.assertRaises(V10ContractError):
            verify_cpt_summary(summary)


class CPTCorpusArtifactTests(unittest.TestCase):
    def test_independent_recount_proves_exact_15m_without_training_claim(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/cpt-corpus-independent-recount.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(report["schema"], "ProofLaunchCPTIndependentRecountV1")
        self.assertEqual(report["status"], "passed_independent_recount_not_training")
        self.assertEqual(report["token_count"], TARGET_CPT_TOKENS)
        self.assertTrue(report["token_count_observed"])
        self.assertEqual(report["record_count"], 10_350)
        self.assertEqual(report["shard_count"], 14)
        self.assertGreaterEqual(report["provider_count"], 10)
        self.assertLessEqual(report["maximum_provider_share"], 0.15)
        self.assertTrue(report["all_record_contracts_revalidated"])
        self.assertTrue(report["all_record_token_counts_reencoded"])
        self.assertTrue(report["all_shard_hashes_verified"])
        self.assertEqual(report["failure_count"], 0)
        self.assertEqual(report["failures"], [])
        for key in (
            "duplicate_record_count",
            "near_duplicate_record_count",
            "unresolved_rights_count",
            "model_output_record_count",
            "evaluation_contamination_count",
            "forbidden_evaluation_class_token_count",
        ):
            self.assertEqual(report[key], 0, key)
        self.assertFalse(report["training_observed"])
        self.assertFalse(report["cpt_checkpoint_observed"])


if __name__ == "__main__":
    unittest.main()
