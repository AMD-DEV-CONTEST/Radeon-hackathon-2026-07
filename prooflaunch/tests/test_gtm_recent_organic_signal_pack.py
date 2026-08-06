from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_recent_organic_signal_pack import (
    RecentOrganicSignalPackError,
    compile_recent_organic_signal_pack,
    merge_recent_organic_signal_packs,
    verify_recent_organic_signal_pack,
)
from prooflaunch_remix.ledger import canonical_json


def _write_fixture(root: Path, *, recent_180: int = 4) -> None:
    plan = {
        "schema": "ProofLaunchOpenSourceSocialCollectionPlanV1",
        "rights": "public_measurement",
        "plans": [
            {
                "source_host": "example.com",
                "platform": "feed",
                "source_url_sha256": "a" * 64,
            }
        ],
        "plan_sha256": "b" * 64,
    }
    intelligence = {
        "schema": "ProofLaunchCreativeSignalIntelligenceV1",
        "top_abstract_format_patterns": [
            {"feature": "image", "observations": 4},
            {"feature": "rss_or_atom", "observations": 3},
        ],
        "metric_summaries": [
            {"metric": "item_count", "observation_count": 1, "minimum": 8, "maximum": 8}
        ],
    }
    intelligence_sha = hashlib.sha256(canonical_json(intelligence).encode()).hexdigest()
    receipt = {
        "schema": "ProofLaunchOpenSourceSocialCollectionRunV2",
        "plan_sha256": plan["plan_sha256"],
        "captured_at": "2026-08-04T12:00:00Z",
        "status": "completed",
        "runs": [
            {
                "status": "completed",
                "connector_id": "feedparser",
                "captcha_or_auth_bypass_attempted": False,
                "organic_signal_summary": {
                    "schema": "ProofLaunchWithinSourceOrganicBaselineV1",
                    "view_measured_item_count": 8,
                    "normalized_item_count": 8,
                    "relative_attention_index_ge_2_count": 2,
                    "top_relative_attention_pattern_counts": {"evidence_led_frame": 2},
                    "raw_expression_retained": False,
                    "public_item_identifiers_retained": False,
                },
                "public_freshness": {
                    "timestamped_item_count": 8,
                    "recent_item_count_90d": 2,
                    "recent_item_count_180d": recent_180,
                    "oldest_publication_at": "2026-03-01T00:00:00Z",
                    "newest_publication_at": "2026-08-02T00:00:00Z",
                },
            }
        ],
        "creative_signal_intelligence_sha256": intelligence_sha,
        "training_admitted": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(canonical_json(receipt).encode()).hexdigest()
    for name, value in (
        ("collection-plan.json", plan),
        ("collection-receipt.json", receipt),
        ("creative-signal-intelligence.json", intelligence),
    ):
        (root / name).write_text(json.dumps(value), encoding="utf-8")


class RecentOrganicSignalPackTests(unittest.TestCase):
    def test_compiles_recent_public_observations_without_source_expression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_fixture(root)
            pack = compile_recent_organic_signal_pack(root)
        verify_recent_organic_signal_pack(pack)
        self.assertEqual(pack["recent_item_count_preferred_window"], 2)
        self.assertEqual(pack["recent_item_count_maximum_window"], 4)
        self.assertFalse(pack["training_admitted"])
        self.assertEqual(pack["organic_measurement_coverage"]["same_source_normalized_item_count"], 8)
        self.assertEqual(pack["organic_measurement_coverage"]["learning_status"], "pending_named_human_approval")
        self.assertEqual(pack["automatic_learning_memory_write_count"], 0)
        self.assertNotIn("caption", json.dumps(pack))
        self.assertIn("not proof of causality", pack["recent_organic_signal_context"])

    def test_rejects_collection_with_no_item_in_maximum_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_fixture(root, recent_180=0)
            with self.assertRaisesRegex(RecentOrganicSignalPackError, "no source item"):
                compile_recent_organic_signal_pack(root)

    def test_merges_verified_packs_without_enabling_memory_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_fixture(root)
            first = compile_recent_organic_signal_pack(root)
            merged = merge_recent_organic_signal_packs([first, first])
        verify_recent_organic_signal_pack(merged)
        self.assertEqual(merged["source_count"], 2)
        self.assertEqual(merged["recent_item_count_maximum_window"], 8)
        self.assertEqual(merged["automatic_learning_memory_write_count"], 0)
        self.assertFalse(merged["training_admitted"])


if __name__ == "__main__":
    unittest.main()
