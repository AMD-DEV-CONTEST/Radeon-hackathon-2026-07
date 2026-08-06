from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_text_challenger import (
    _SCENARIO_DIMENSIONS,
    _scenario_lens_from_values,
    _scenario_territories,
)


class CreativeScenarioLensTests(unittest.TestCase):
    def test_all_48_scenario_combinations_have_distinct_bound_variants(self) -> None:
        signatures: set[str] = set()
        portfolios: set[tuple[str, ...]] = set()
        for business_model in ("b2b", "b2c"):
            for lifecycle in ("pre_pmf", "launch", "growth", "mature"):
                for budget in ("zero", "small", "scaled"):
                    for industry_risk in ("standard", "high_regulation"):
                        lens = _scenario_lens_from_values(
                            {
                                "business_model": business_model,
                                "lifecycle": lifecycle,
                                "budget": budget,
                                "industry_risk": industry_risk,
                            }
                        )
                        territories = _scenario_territories(lens)
                        signatures.add(lens["signature"])
                        portfolios.add(
                            tuple(row["variant_id"] for row in territories)
                        )
                        self.assertEqual(len(territories), 3)
                        self.assertEqual(
                            set(lens["dimensions"]), set(_SCENARIO_DIMENSIONS)
                        )
                        self.assertTrue(
                            all(
                                row["scenario_signature"] == lens["signature"]
                                for row in territories
                            )
                        )
        self.assertEqual(len(signatures), 48)
        self.assertEqual(len(portfolios), 48)

    def test_unknown_dimension_value_fails_closed(self) -> None:
        with self.assertRaises(KeyError):
            _scenario_lens_from_values(
                {
                    "business_model": "b2b",
                    "lifecycle": "growth",
                    "budget": "unbounded",
                    "industry_risk": "standard",
                }
            )


if __name__ == "__main__":
    unittest.main()
