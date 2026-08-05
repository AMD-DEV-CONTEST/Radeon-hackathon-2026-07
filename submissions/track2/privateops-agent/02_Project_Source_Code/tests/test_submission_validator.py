import tempfile
import unittest
import json
from pathlib import Path

from scripts.verify_submission import validate


class SubmissionValidatorTests(unittest.TestCase):
    def test_missing_artifacts_and_unresolved_markers_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "submission").mkdir()
            (root / "submission" / "README.md").write_text("TODO replace this", encoding="utf-8")

            problems = validate(root)

            self.assertTrue(any("missing or empty" in item for item in problems))
            self.assertIn("missing or empty: submission/PrivateOps-Agent-Competition-Deck.pptx", problems)
            self.assertTrue(any("forbidden marker" in item for item in problems))

    def test_stale_placeholder_benchmark_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submission = root / "submission"
            submission.mkdir()
            (submission / "benchmark-evidence.json").write_text(
                json.dumps({"status": "awaiting_account_owner_radeon_cloud_capture", "runs": []}),
                encoding="utf-8",
            )

            problems = validate(root)

            self.assertIn("benchmark evidence is still a pre-capture placeholder", problems)

    def test_copied_benchmark_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "submission" / "evidence" / "rocm-verified"
            evidence.mkdir(parents=True)
            source = {
                "run_id": "bench-real",
                "provider_mode": "rocm-local",
                "verified": True,
                "gpu_name": "AMD Radeon Graphics",
                "rocm_version": "7.2.1",
                "model_name": "Qwen/Qwen2.5-7B-Instruct",
                "latency_ms": 1511.072,
                "tokens_per_second": 32.427,
                "prompt_tokens": 45,
                "completion_tokens": 49,
            }
            (evidence / "radeon-benchmark-run.json").write_text(json.dumps(source), encoding="utf-8")
            (evidence / "rocm-agent-live-latency-zh.txt").write_text("18.384639", encoding="utf-8")
            copied = {"schema_version": "1.0", "status": "verified_radeon_rocm_capture", "runs": [{**source, "latency_ms": 999.0, "agent_latency_ms": 18384.639}]}
            (root / "submission" / "benchmark-evidence.json").write_text(json.dumps(copied), encoding="utf-8")

            problems = validate(root)

            self.assertIn("benchmark evidence drifted from immutable Radeon source", problems)

    def test_stale_competition_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submission = root / "submission"
            submission.mkdir()
            (submission / "README.md").write_text(
                "READY FOR REAL CLOUD EVIDENCE and awaiting_account_owner_radeon_cloud_capture",
                encoding="utf-8",
            )

            problems = validate(root)

            self.assertTrue(any("stale competition copy in submission/README.md" in item for item in problems))

    def test_angle_bracket_submission_placeholder_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submission = root / "submission"
            submission.mkdir()
            (submission / "pr-submission.md").write_text(
                "Final demonstration video: <ADD PUBLIC VIDEO URL>.",
                encoding="utf-8",
            )

            problems = validate(root)

            self.assertTrue(any("forbidden marker" in item for item in problems))

    def test_permission_first_and_measured_proof_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            submission = root / "submission"
            submission.mkdir()
            (root / "README.md").write_text("LangChain Qwen/Qwen2.5-7B-Instruct ROCm", encoding="utf-8")
            (submission / "project-specification.html").write_text(
                "LangChain Core Qwen/Qwen2.5-7B-Instruct",
                encoding="utf-8",
            )

            problems = validate(root)

            self.assertIn(
                "missing required competition detail in README.md: Broad visibility. Deliberate action. Evidence for every decision.",
                problems,
            )
            self.assertIn(
                "missing required competition detail in submission/project-specification.html: 1,511.072",
                problems,
            )
            self.assertIn(
                "missing required competition detail in README.md: Remote model / Local ROCm",
                problems,
            )


if __name__ == "__main__":
    unittest.main()
