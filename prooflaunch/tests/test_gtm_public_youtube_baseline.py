from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_public_youtube_baseline import PublicYoutubeBaselineError, compile_public_youtube_baseline, verify


def fixture():
    config = {
        "schema": "ProofLaunchPublicYoutubeNamedProductBaselineAnalysisDraftV1",
        "as_of_date": "2026-08-03",
        "window_days": 180,
        "minimum_recent_items_for_full_sample": 3,
        "sources": [
            {"source_index": index, "product": f"Product {index}", "expected_channel": f"Channel {index}", "pk_lanes": ["text_content_generation"]}
            for index in range(1, 11)
        ],
        "truth_boundary": "fixture boundary",
    }
    payloads = {
        index: {
            "channel": f"Channel {index}",
            "channel_is_verified": index % 2 == 0,
            "channel_follower_count": 1000 * index,
            "entries": [
                {"id": f"{index}-{row}", "title": "How to build a demo", "upload_date": f"202607{row + 10:02d}", "duration": 30 + row * 90, "view_count": index * row * 2_000_000, "like_count": row * 100, "comment_count": row * 10}
                for row in range(1, 4)
            ],
        }
        for index in range(1, 11)
    }
    bindings = [{"source_index": index, "sha256": f"{index:064x}"[-64:]} for index in range(1, 11)]
    return config, payloads, bindings


class PublicYoutubeBaselineTests(unittest.TestCase):
    def test_compiles_ten_named_products_without_retaining_titles(self) -> None:
        config, payloads, bindings = fixture()
        result = compile_public_youtube_baseline(config, source_payloads=payloads, source_bindings=bindings)
        verify(result)
        self.assertEqual(result["named_product_count"], 10)
        self.assertEqual(result["full_sample_product_count"], 10)
        self.assertEqual(len(result["clean_room_execution_hypotheses"]), 3)
        self.assertNotIn("How to build", str(result))
        self.assertFalse(result["interpretation_contract"]["distribution_outlier_is_viral_proof"])

    def test_rejects_channel_identity_drift(self) -> None:
        config, payloads, bindings = fixture()
        mutated = copy.deepcopy(payloads)
        mutated[1]["channel"] = "Impostor"
        with self.assertRaises(PublicYoutubeBaselineError):
            compile_public_youtube_baseline(config, source_payloads=mutated, source_bindings=bindings)


if __name__ == "__main__":
    unittest.main()
