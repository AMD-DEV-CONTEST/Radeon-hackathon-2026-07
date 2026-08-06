from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_generative_execution_kernel import (
    AXES,
    CAPABILITY_LANES,
    compile_generative_execution_kernel,
    verify_generative_execution_kernel,
)


def brief(*, business_model: str, lifecycle: str, platform: str, suffix: str) -> dict[str, str]:
    return {
        "brief_id": f"brief-{suffix}", "business_model": business_model, "lifecycle": lifecycle,
        "industry": "developer tools" if business_model == "b2b" else "consumer productivity",
        "category": "AI GTM employee" if business_model == "b2b" else "private memory",
        "product_surface": "web_agent" if business_model == "b2b" else "mobile_app",
        "platform": platform, "audience": "revenue operators" if business_model == "b2b" else "busy private reflectors",
        "decision_job": "decide whether the system deserves evaluation" if business_model == "b2b" else "remember without performance pressure",
        "tension": "output volume hides release judgment" if business_model == "b2b" else "camera rolls preserve evidence but not meaning",
        "approved_proof": "one owner-supplied workflow exists" if business_model == "b2b" else "one synthetic private ritual is defined",
        "brand_voice": "specific, unexpected, calm", "budget": "zero",
    }


class GTMGenerativeExecutionKernelTests(unittest.TestCase):
    def test_b2b_and_b2c_batches_are_large_diverse_and_non_executing(self) -> None:
        cases = [
            brief(business_model="b2b", lifecycle="launch", platform="linkedin", suffix="b2b-linkedin"),
            brief(business_model="b2b", lifecycle="growth", platform="reddit", suffix="b2b-reddit"),
            brief(business_model="b2c", lifecycle="launch", platform="tiktok", suffix="b2c-tiktok"),
            brief(business_model="b2c", lifecycle="growth", platform="instagram", suffix="b2c-instagram"),
        ]
        for source in cases:
            kernel = compile_generative_execution_kernel(source, candidate_count=24)
            verify_generative_execution_kernel(kernel)
            self.assertEqual(len(kernel["candidate_blueprints"]), 24)
            self.assertGreaterEqual(kernel["creative_genome"]["minimum_pairwise_axis_distance"], 3)
            self.assertGreater(kernel["creative_genome"]["blueprint_design_space"], 1_000_000)
            self.assertEqual(kernel["generated_content_count"], 0)
            self.assertEqual(kernel["external_action_count"], 0)
            self.assertFalse(kernel["candidate_funnel"]["automatic_winner_selection"])
            self.assertEqual(len(kernel["evaluation_axes"]), 12)
            self.assertEqual(len(kernel["capability_lane_graph"]), 13)
            self.assertFalse(kernel["open_source_modification_contract"]["automatic_install_or_adapter_promotion"])

    def test_prior_genomes_are_excluded_from_next_batch(self) -> None:
        source = brief(business_model="b2c", lifecycle="launch", platform="tiktok", suffix="repeat")
        first = compile_generative_execution_kernel(source, candidate_count=24)
        prior = [row["genome_id"] for row in first["candidate_blueprints"]]
        second = compile_generative_execution_kernel(source, prior_genome_ids=prior, candidate_count=24)
        self.assertTrue(set(prior).isdisjoint(row["genome_id"] for row in second["candidate_blueprints"]))
        self.assertEqual(second["creative_genome"]["prior_genome_exclusion_count"], 24)

    def test_axis_registry_has_real_combinatorial_depth(self) -> None:
        self.assertEqual(len(AXES), 8)
        self.assertTrue(all(len(options) >= 8 for options in AXES.values()))
        self.assertEqual(len(CAPABILITY_LANES), 13)
        self.assertEqual(len({row["id"] for row in CAPABILITY_LANES}), 13)


if __name__ == "__main__":
    unittest.main()
