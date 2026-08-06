"""Todo 5 tests: typed API contracts, run_eval metric computation, report schema.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path("/persistent/learning-companion")
sys.path.insert(0, str(ROOT))


def sh(*args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT, timeout=60)


class TestContracts(unittest.TestCase):
    def test_contracts_module_imports_and_models_typed(self) -> None:
        from app import contracts
        self.assertTrue(hasattr(contracts, "SkillDetailOut"))
        self.assertTrue(hasattr(contracts, "EvalReport"))
        # SkillDetailOut requires the typed fields
        s = contracts.SkillDetailOut(
            id=1, name="x", growth_value=0.0, decay_rate=3.0, status="萌芽",
            created_at="t", updated_at="t")
        self.assertEqual(s.cards, [])

    def test_report_schema_valid_json(self) -> None:
        json.load(open(f"{ROOT}/docs/report-schema.json"))

    def test_api_gen_types_exist(self) -> None:
        gen = ROOT / "web/src/lib/api.gen.ts"
        self.assertTrue(gen.exists(), "api.gen.ts missing (run audit_contracts.sh)")


class TestRunEval(unittest.TestCase):
    def test_valid_responses_produce_exact_metrics(self) -> None:
        out = "/tmp/lc-eval-valid.json"
        r = sh("python3", "scripts/run_eval.py",
               "--fixtures", f"{ROOT}/eval/fixtures",
               "--manifest", f"{ROOT}/eval/fixtures/manifest.json",
               "--responses", f"{ROOT}/eval/fixtures/golden-valid-response.json",
               "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.load(open(out))
        # all 3 cards supported, no unsupported/duplicate, full coverage, grading pass
        self.assertEqual(rep["metrics"]["source_support"], 100.0)
        self.assertEqual(rep["metrics"]["unsupported_claim"], 0.0)
        self.assertEqual(rep["metrics"]["duplicate"], 0.0)
        self.assertEqual(rep["metrics"]["grading_agreement"], 100.0)
        self.assertEqual(rep["fatal_failures"], [])
        # schema validity via json schema
        import jsonschema
        schema = json.load(open(f"{ROOT}/docs/report-schema.json"))
        jsonschema.validate(rep, schema)

    def test_malformed_response_counts_fatal(self) -> None:
        out = "/tmp/lc-eval-fail.json"
        r = sh("python3", "scripts/run_eval.py",
               "--fixtures", f"{ROOT}/eval/fixtures",
               "--manifest", f"{ROOT}/eval/fixtures/manifest.json",
               "--responses", f"{ROOT}/eval/fixtures/golden-malformed-response.json",
               "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.load(open(out))
        self.assertTrue(any(f["condition"] == "unparseable_json" for f in rep["fatal_failures"]))


class TestAuditContracts(unittest.TestCase):
    def test_audit_contracts_passes(self) -> None:
        r = sh("bash", "scripts/audit_contracts.sh")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
