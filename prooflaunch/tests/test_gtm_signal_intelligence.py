from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_signal_intelligence import (
    SignalIntelligenceError,
    compile_signal_intelligence,
)


def snapshot() -> dict[str, object]:
    signals = []
    for index, platform in enumerate(("TikTok", "TikTok", "YouTube", "YouTube", "LinkedIn"), start=1):
        signals.append(
            {
                "signal_id": f"signal-{index}",
                "platform": platform,
                "source_kind": "official_platform_api",
                "source_uri": f"https://api.example.test/metrics/{index}",
                "observed_at": "2026-08-01T12:00:00+00:00",
                "rights": "public_measurement",
                "metric": "engagement_rate",
                "value": 0.02 * index,
                "sample_size": 1_000 * index,
                "format_features": ["proof_demo", "first_2s_hook"],
            }
        )
    return {
        "schema": "ProofLaunchCreativeSignalSnapshotV1",
        "captured_at": "2026-08-01T12:05:00+00:00",
        "purpose": "creative experiment planning",
        "retention_days": 30,
        "contains_personal_data": False,
        "contains_copied_creative": False,
        "signals": signals,
    }


class SignalIntelligenceTests(unittest.TestCase):
    def test_authorized_metrics_become_abstract_hypotheses_without_copy(self) -> None:
        result = compile_signal_intelligence(snapshot())
        self.assertTrue(result["evidence_sufficient_for_hypothesis_generation"])
        self.assertEqual(result["signal_count"], 5)
        self.assertEqual(len(result["hypotheses"]), 2)
        self.assertFalse(result["strategy_mutation_executed"])
        self.assertFalse(result["copied_creative_retained"])
        self.assertNotIn("source_uri", result["source_evidence"][0])
        self.assertRegex(
            result["source_evidence"][0]["source_uri_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_raw_caption_media_or_user_identifiers_fail_closed(self) -> None:
        for field in ("caption", "script", "media_url", "user_id"):
            payload = snapshot()
            payload["signals"][0][field] = "must not enter training or strategy context"
            with self.subTest(field=field), self.assertRaisesRegex(
                SignalIntelligenceError, "forbidden"
            ):
                compile_signal_intelligence(payload)

    def test_unknown_source_rights_or_pii_fail_closed(self) -> None:
        payload = snapshot()
        payload["signals"][0]["source_kind"] = "scraped_without_permission"
        with self.assertRaisesRegex(SignalIntelligenceError, "not authorized"):
            compile_signal_intelligence(payload)
        payload = snapshot()
        payload["signals"][0]["rights"] = "unknown"
        with self.assertRaisesRegex(SignalIntelligenceError, "rights"):
            compile_signal_intelligence(payload)
        payload = snapshot()
        payload["contains_personal_data"] = True
        with self.assertRaisesRegex(SignalIntelligenceError, "no PII"):
            compile_signal_intelligence(payload)

    def test_large_public_counts_are_admitted_without_widening_rate_bounds(self) -> None:
        payload = snapshot()
        payload["signals"][0]["metric"] = "view_count"
        payload["signals"][0]["value"] = 5_397_427
        result = compile_signal_intelligence(payload)
        view_summary = next(
            row for row in result["metric_summaries"] if row["metric"] == "view_count"
        )
        self.assertEqual(view_summary["maximum"], 5_397_427.0)

        too_large = snapshot()
        too_large["signals"][0]["metric"] = "view_count"
        too_large["signals"][0]["value"] = 1_000_000_000_001
        with self.assertRaisesRegex(SignalIntelligenceError, "metric value"):
            compile_signal_intelligence(too_large)

        impossible_rate = snapshot()
        impossible_rate["signals"][0]["metric"] = "engagement_rate"
        impossible_rate["signals"][0]["value"] = 1_000_001
        with self.assertRaisesRegex(SignalIntelligenceError, "metric value"):
            compile_signal_intelligence(impossible_rate)

    def test_point_in_time_growth_cases_compile_to_hypotheses_without_source_copy(self) -> None:
        payload = snapshot()
        payload["growth_cases"] = [
            {
                "case_id": f"case-{index}",
                "category": "developer tools",
                "platform": "LinkedIn",
                "market": "US",
                "observed_at": "2026-08-01T11:00:00+00:00",
                "source_uri_sha256": f"{index + 1:064x}"[-64:],
                "rights": "public_measurement",
                "windows": {
                    str(window): {
                        "active_audience_growth_rate": 0.02 + index / 100,
                        "qualified_engagement_rate": 0.01 + index / 1000,
                        "conversion_signal_rate": 0.005 + index / 2000,
                        "content_supply_growth_rate": 0.03 + index / 1000,
                        "sample_size": 2_000 + index,
                    }
                    for window in (28, 90, 180)
                },
                "category_benchmarks": {
                    str(window): {
                        "active_audience_growth_rate": 0.03,
                        "qualified_engagement_rate": 0.015,
                        "conversion_signal_rate": 0.007,
                        "content_supply_growth_rate": 0.04,
                    }
                    for window in (28, 90, 180)
                },
            }
            for index in range(10)
        ]
        result = compile_signal_intelligence(payload)
        radar = result["growth_case_radar"]
        self.assertEqual(radar["eligible_case_count"], 10)
        self.assertFalse(radar["copied_creative_retained"])
        self.assertFalse(radar["automatic_strategy_mutation_executed"])


if __name__ == "__main__":
    unittest.main()
