from __future__ import annotations

import unittest

from scripts.run_local_mlx_multimodal_factory_text import (
    adapt_claim_inventory,
    candidate_failures,
    portfolio_failures,
)


class RunLocalMLXMultimodalFactoryTextTests(unittest.TestCase):
    def test_mechanical_gate_accepts_complete_candidate_and_rejects_claim_drift(self) -> None:
        factory = {
            "brief": {"approved_proof": "One approved proof exists."},
            "candidate_campaigns": [{
                "campaign_spine": {},
                "text_generation_request": {"stress_pack": [{"reference_products": ["Named Competitor"]}]}
            }],
        }
        candidate = {
            "strategy_rationale": "Operators need one inspectable decision artifact before another automation promise enters committee review.",
            "platform_native_primary_copy": {
                "first_line": "The dashboard hid the only sequence the operator needed.",
                "body": [
                    "A plant reliability lead does not need another confident summary.",
                    "They need the failure sequence, its source, and the unresolved condition in one view.",
                    "Inspect the replay before deciding whether the bounded pilot deserves a review.",
                ],
                "proof": "One approved proof exists.",
                "participation": "Name the missing condition that would stop the pilot.",
                "cta": "Review one bounded fault replay.",
            },
            "alternate_openings": [f"Distinct substantive opening number {index}." for index in range(5)],
            "decision_tool": {
                "name": "The Missing Condition Test",
                "steps": [
                    "Freeze the exact operating decision under review.",
                    "Separate the observed event from the inferred cause.",
                    "Name the missing condition that would stop the pilot.",
                ],
                "kill_rule": "Stop when the replay cannot change a bounded operating decision.",
                "privacy_boundary": "Use synthetic event labels and never paste confidential plant data.",
            },
            "comment_or_reply_system": {
                "first_comment": "The useful question is which event cannot yet be explained.",
                "objection_branches": [
                    {"objection": "The replay may omit context.", "reply": "Name the missing evidence boundary before evaluating the inference."},
                    {"objection": "The sequence may be incomplete.", "reply": "Separate each observed event from the inferred cause."},
                    {"objection": "The pilot may be premature.", "reply": "Route the unresolved condition to review before any commitment."},
                ],
            },
            "seo_geo_derivatives": {
                "search_explainer": "A fault replay preserves the observed event sequence, evidence source and unresolved inference for review.",
                "answer_engine_citation_unit": "The bounded demonstration is the only approved proof; broader operating outcomes remain hypotheses.",
            },
            "claim_inventory": [{"claim": "One approved proof exists.", "status": "approved_proof", "evidence": "One approved proof exists."}],
            "genome_execution": {
                "hook_mechanism": "open on the decision conflict",
                "narrative_mechanism": "show the observed sequence before inference",
                "proof_mechanism": "One approved proof exists.",
                "interaction_mechanism": "ask for the missing condition",
            },
        }
        self.assertEqual(candidate_failures(candidate, factory=factory), ())
        candidate["platform_native_primary_copy"]["body"][0] = "This will drive revenue."
        self.assertIn("candidate contains an unsupported effect or quality claim", candidate_failures(candidate, factory=factory))

    def test_bounded_adapter_only_clamps_claim_labels(self) -> None:
        candidate = {
            "platform_native_primary_copy": {"body": ["Do not rewrite this creative sentence."]},
            "claim_inventory": [
                {"claim": "Unapproved capability", "status": "approved_proof", "evidence": "wrong"},
            ],
        }
        adapted, changes = adapt_claim_inventory(candidate, approved_proof="Exact approved proof")
        self.assertEqual(adapted["platform_native_primary_copy"], candidate["platform_native_primary_copy"])
        self.assertEqual(changes, 2)
        self.assertEqual(adapted["claim_inventory"], [
            {"claim": "Unapproved capability", "status": "hypothesis", "evidence": "none; requires owner evidence"},
            {"claim": "Exact approved proof", "status": "approved_proof", "evidence": "Exact approved proof"},
        ])

    def test_portfolio_gate_rejects_duplicate_first_lines(self) -> None:
        candidate = {
            "platform_native_primary_copy": {
                "first_line": "The same opening must not survive twice.",
                "body": ["One concrete body block about a bounded decision."],
            },
            "decision_tool": {
                "name": "Bounded test", "steps": ["Apply one bounded step."],
                "kill_rule": "Stop when no decision changes.", "privacy_boundary": "Use synthetic inputs only.",
            },
        }
        rows = [
            {"candidate_id": "a", "candidate": candidate},
            {"candidate_id": "b", "candidate": candidate},
        ]
        failures = portfolio_failures(rows)
        self.assertIn("portfolio repeats a primary first line", failures)


if __name__ == "__main__":
    unittest.main()
