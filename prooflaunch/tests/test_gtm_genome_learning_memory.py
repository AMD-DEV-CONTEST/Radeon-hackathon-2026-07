from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_genome_learning_memory import (
    GTMGenomeLearningMemoryError,
    compile_genome_learning_memory,
)
from prooflaunch_remix.gtm_generative_execution_kernel import compile_generative_execution_kernel


BRIEF = {
    "brief_id": "memory-test", "business_model": "b2c", "lifecycle": "launch", "industry": "consumer productivity",
    "category": "private memory", "product_surface": "mobile_app", "platform": "tiktok", "audience": "private reflectors",
    "decision_job": "remember without performance", "tension": "camera roll evidence does not preserve meaning",
    "approved_proof": "one synthetic ritual exists", "brand_voice": "specific, warm, surprising", "budget": "zero",
}


def observation(*, verdict: str, pairs: list[str], record_id: str) -> dict[str, object]:
    return {
        "record_id": record_id, "genome_id": "a" * 64, "verdict": verdict, "business_model": "b2c",
        "platform": "tiktok", "category": "private memory", "axis_pairs": pairs, "evidence_sha256": "b" * 64,
        "approved_by": "human-creative-owner", "human_approved": True,
    }


class GTMGenomeLearningMemoryTests(unittest.TestCase):
    def test_unapproved_memory_is_rejected(self) -> None:
        row = observation(verdict="retire", pairs=["hook:forbidden_move"], record_id="r1")
        row["human_approved"] = False
        with self.assertRaisesRegex(GTMGenomeLearningMemoryError, "unapproved"):
            compile_genome_learning_memory([row])

    def test_promoted_and_retired_patterns_change_next_batch_without_current_mutation(self) -> None:
        memory = compile_genome_learning_memory([
            observation(verdict="promote", pairs=["hook:category_inversion"], record_id="promote-1"),
            observation(verdict="retire", pairs=["tone:deadpan_contrarian", "proof:transparent_failure"], record_id="retire-1"),
        ])
        kernel = compile_generative_execution_kernel(BRIEF, candidate_count=24, learning_memory=memory)
        self.assertEqual(kernel["creative_genome"]["applicable_learning_record_count"], 2)
        self.assertEqual(kernel["creative_genome"]["promoted_pattern_count"], 1)
        self.assertEqual(kernel["creative_genome"]["retired_pattern_count"], 1)
        self.assertGreater(kernel["candidate_blueprints"][0]["learning_prior_score"], 0)
        self.assertLessEqual(kernel["creative_genome"]["learned_prior_selected_count"], 18)
        self.assertGreaterEqual(kernel["creative_genome"]["novel_exploration_selected_count"], 6)
        self.assertEqual(
            sum(row["selection_mode"] == "novel_exploration" for row in kernel["candidate_blueprints"]),
            kernel["creative_genome"]["novel_exploration_selected_count"],
        )
        for candidate in kernel["candidate_blueprints"]:
            genome = candidate["genome"]
            self.assertFalse(genome["tone"]["id"] == "deadpan_contrarian" and genome["proof"]["id"] == "transparent_failure")
        self.assertFalse(kernel["generalization_contract"]["current_run_self_mutation"])


if __name__ == "__main__":
    unittest.main()
