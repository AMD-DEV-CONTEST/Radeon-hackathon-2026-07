from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_strategy_challenger import (
    GTMStrategyChallengerError,
    compile_strategy_challenger_receipt,
    extract_strategy_candidate,
    strategy_candidate_failures,
    validate_strategy_candidate,
    validate_strategy_challenger_receipt,
)


def _candidate() -> dict:
    return {
        "strategy": (
            "Recruit cybersecurity CTO buying groups that need an inspectable launch process; "
            "differentiate with a reviewable evidence workspace and explicit claim boundaries."
        ),
        "primary_channel": "LinkedIn",
        "channel_rationale": (
            "The buying group already exchanges technical operating lessons there, allowing "
            "the team to contribute useful decision artifacts before requesting a conversation."
        ),
        "zero_budget_loop": [
            "Publish a claim-bound teardown and reusable evidence checklist from the founder account.",
            "Invite security operators in two moderated communities to challenge one checklist assumption.",
            "Co-create a revised diagnostic with consenting participants and credit their contribution.",
            "Share the revision with a small matched outreach list and log each qualified conversation request.",
        ],
        "experiment": {
            "treatment": "Send the evidence checklist plus the co-created diagnostic to the treatment group.",
            "comparable_baseline": "Keep a randomized same-window holdout on the existing organic sequence only.",
            "observation_window_days": 14,
            "primary_metric": "qualified_conversations",
            "decision_rule": "Proceed to human review only when treatment has at least 4 qualified conversations and exceeds holdout by 2.",
        },
        "human_gate": {
            "role": "named GTM lead",
            "decision": "approve_or_reject",
            "artifact": "hash-bound experiment packet and qualified-conversation ledger",
        },
        "unsupported_claims": [
            "The workspace guarantees revenue or a shorter sales cycle.",
            "The campaign will become an annual category breakout.",
        ],
    }


class GTMStrategyChallengerTests(unittest.TestCase):
    def test_rights_safe_zero_budget_candidate_passes_frozen_contract(self) -> None:
        validated = validate_strategy_candidate(_candidate())
        self.assertEqual(validated["schema"], "ProofLaunchZeroBudgetStrategyCandidateV1")
        self.assertEqual(len(validated["content_sha256"]), 64)

    def test_unproven_effect_and_weak_baseline_fail_together(self) -> None:
        candidate = _candidate()
        candidate["strategy"] += " It increases close rates by 15%."
        candidate["experiment"]["comparable_baseline"] = (
            "Compare with the current lead generation rate from ordinary inbound inquiries."
        )
        failures = strategy_candidate_failures(candidate)
        self.assertIn("strategy contains an unproven effect claim", failures)
        self.assertTrue(any("same-window holdout" in item for item in failures))

    def test_vanity_loop_and_unassigned_holdout_do_not_pass_as_effect_design(self) -> None:
        candidate = _candidate()
        candidate["zero_budget_loop"][-1] = (
            "Monitor checklist downloads, likes, comments, and general community engagement."
        )
        candidate["experiment"]["comparable_baseline"] = (
            "Same-window holdout: do not share the checklist in a third community."
        )
        candidate["human_gate"]["artifact"] = "engagement report and download dashboard"
        failures = strategy_candidate_failures(candidate)
        self.assertTrue(any("vanity engagement" in item for item in failures))
        self.assertTrue(any("assignment" in item for item in failures))
        self.assertTrue(any("qualified-conversation ledger" in item for item in failures))

    def test_share_plus_active_engagement_are_two_earned_mechanisms(self) -> None:
        candidate = _candidate()
        candidate["zero_budget_loop"] = [
            "Identify two moderated product communities with explicit contribution rules.",
            "Share a reusable evidence worksheet and invite members to challenge one assumption.",
            "Actively engage in the discussion and log each resulting qualified conversation.",
            "Publish a revised worksheet that credits consenting community contributors.",
        ]
        self.assertEqual(strategy_candidate_failures(candidate), ())

    def test_truncated_json_never_reaches_validation(self) -> None:
        with self.assertRaisesRegex(GTMStrategyChallengerError, "complete JSON"):
            extract_strategy_candidate('{"strategy":"unfinished"')

    def test_bounded_repair_receipt_is_truthful_and_tamper_evident(self) -> None:
        rejected = _candidate()
        rejected["strategy"] += " It guarantees revenue."
        accepted = _candidate()
        receipt = compile_strategy_challenger_receipt(
            model_id="mlx-community/gemma-3-12b-it-4bit",
            model_revision="revision-1",
            model_manifest_sha256="a" * 64,
            device_family="Apple Metal",
            attempts=(
                {"raw_output": __import__("json").dumps(rejected), "elapsed_seconds": 1, "generated_token_count": 100},
                {"raw_output": __import__("json").dumps(accepted), "elapsed_seconds": 1, "generated_token_count": 120},
            ),
        )
        validate_strategy_challenger_receipt(receipt)
        self.assertTrue(receipt["accepted"])
        self.assertFalse(receipt["causal_effect_claim_eligible"])
        self.assertIsNotNone(receipt["attempts"][0]["candidate_snapshot"])
        self.assertEqual(
            receipt["attempts"][1]["candidate_snapshot"]["primary_channel"],
            "LinkedIn",
        )
        tampered = copy.deepcopy(receipt)
        tampered["automatic_release_authority"] = True
        with self.assertRaisesRegex(GTMStrategyChallengerError, "digest"):
            validate_strategy_challenger_receipt(tampered)


if __name__ == "__main__":
    unittest.main()
