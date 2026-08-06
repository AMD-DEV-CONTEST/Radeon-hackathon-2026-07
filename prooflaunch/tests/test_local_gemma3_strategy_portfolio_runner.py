from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_strategy_portfolio import (
    compile_strategy_portfolio_receipt,
    load_portfolio_cases,
)
from tests.test_gtm_strategy_portfolio import candidate


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_local_gemma3_strategy_portfolio.py"
SPEC = importlib.util.spec_from_file_location("local_gemma3_strategy_portfolio", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load local Gemma strategy portfolio runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class LocalGemma3StrategyPortfolioRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load_portfolio_cases(
            json.loads(
                (ROOT / "config/local-gemma3-zero-budget-strategy-portfolio-v1.json").read_text(
                    encoding="utf-8"
                )
            )
        )

    def receipt(self) -> dict[str, object]:
        return compile_strategy_portfolio_receipt(
            model_id=RUNNER.RUNNER.MODEL_ID,
            model_revision="immutable-revision",
            model_manifest_sha256="a" * 64,
            device_family="Apple Metal",
            cases=self.cases,
            case_attempts={
                case["case_id"]: [{"raw_output": json.dumps(candidate(case))}]
                for case in self.cases
            },
        )

    def test_verified_resume_reuses_only_content_bound_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            receipt = self.receipt()
            path.write_text(json.dumps(receipt), encoding="utf-8")
            results = RUNNER._load_prior_results(
                path,
                cases=self.cases,
                revision="immutable-revision",
                manifest_sha256="a" * 64,
            )
            attempt = RUNNER._prior_candidate_as_attempt(results[self.cases[0]["case_id"]])
            self.assertNotIn("content_sha256", attempt["raw_output"])
            self.assertIn(self.cases[0]["case_id"], attempt["raw_output"])

    def test_resume_rejects_model_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(self.receipt()), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "model identity"):
                RUNNER._load_prior_results(
                    path,
                    cases=self.cases,
                    revision="different-revision",
                    manifest_sha256="a" * 64,
                )

    def test_repair_prompt_names_required_baseline_literals(self) -> None:
        prompt = RUNNER._repair_prompt(
            "task",
            "draft",
            (
                "experiment.comparable_baseline must bind matched/randomized/split assignment to a same-window holdout",
            ),
        )
        for literal in (
            "same eligible account pool",
            "randomly split 50/50",
            "same-window treatment",
            "holdout",
        ):
            self.assertIn(literal, prompt)


if __name__ == "__main__":
    unittest.main()
