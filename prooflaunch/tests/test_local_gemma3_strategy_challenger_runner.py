from __future__ import annotations

import importlib.util
import copy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_local_gemma3_strategy_challenger.py"
SPEC = importlib.util.spec_from_file_location("local_gemma3_strategy_challenger", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load local Gemma strategy challenger")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class LocalGemma3StrategyChallengerRunnerTests(unittest.TestCase):
    def test_model_manifest_binds_revision_names_sizes_and_blob_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "immutable-revision-123"
            snapshot.mkdir()
            for name in (
                "config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "model.safetensors.index.json",
                "model-00001-of-00001.safetensors",
            ):
                (snapshot / name).write_text(name, encoding="utf-8")
            revision, digest = RUNNER._model_manifest(snapshot)
            self.assertEqual(revision, "immutable-revision-123")
            self.assertEqual(len(digest), 64)
            (snapshot / "config.json").write_text("changed", encoding="utf-8")
            self.assertNotEqual(RUNNER._model_manifest(snapshot)[1], digest)

    def test_repair_prompt_contains_only_bounded_draft_and_exact_failures(self) -> None:
        prompt = RUNNER._repair_prompt("x" * 7_000, ("first failure", "second failure"))
        self.assertIn("first failure", prompt)
        self.assertIn("second failure", prompt)
        self.assertLess(len(prompt), len(RUNNER.TASK_PROMPT) + 6_500)
        self.assertIn("Rewrite the full JSON from scratch", prompt)

    def test_prior_receipt_requires_hash_and_authority_integrity(self) -> None:
        candidate = {
            "strategy": "A" * 90,
            "primary_channel": "community",
            "channel_rationale": "B" * 60,
            "zero_budget_loop": ["C" * 50] * 4,
            "experiment": {
                "treatment": "D" * 50,
                "comparable_baseline": "E" * 50,
                "observation_window_days": 14,
                "primary_metric": "qualified_conversations",
                "decision_rule": "F" * 60,
            },
            "human_gate": {"role": "lead", "decision": "approve_or_reject", "artifact": "G" * 60},
            "unsupported_claims": ["H" * 20],
        }
        # Compile under a controlled bypass by reusing a valid candidate from the module tests is
        # undesirable here; only the hash verifier is in scope, so construct the signed envelope.
        candidate_envelope = {
            "schema": "ProofLaunchZeroBudgetStrategyCandidateV1",
            **candidate,
        }
        candidate_envelope["content_sha256"] = RUNNER.hashlib.sha256(
            RUNNER._canonical(candidate_envelope).encode("utf-8")
        ).hexdigest()
        receipt = {
            "schema": "ProofLaunchLocalStrategyChallengerReceiptV1",
            "execution": {"network_download_performed": False},
            "accepted_candidate": candidate_envelope,
            "automatic_release_authority": False,
            "automatic_training_admission": False,
            "four_a_claim_eligible": False,
            "top1_claim_eligible": False,
            "causal_effect_claim_eligible": False,
        }
        receipt["content_sha256"] = RUNNER.hashlib.sha256(
            RUNNER._canonical(receipt).encode("utf-8")
        ).hexdigest()
        self.assertEqual(RUNNER._verified_prior_candidate(receipt)[1], receipt["content_sha256"])
        tampered = copy.deepcopy(receipt)
        tampered["automatic_release_authority"] = True
        with self.assertRaisesRegex(SystemExit, "digest"):
            RUNNER._verified_prior_candidate(tampered)


if __name__ == "__main__":
    unittest.main()
