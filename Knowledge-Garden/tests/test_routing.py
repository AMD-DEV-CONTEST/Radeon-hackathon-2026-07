"""Todo 6 tests: A/B routing decision + stub report + digest validation.

Covers the plan's routing pseudocode (threshold_version 1), adversarial
conditions (fatal qwen3, sub-2pp gains, tampered reports), and the READ-ONLY
logical-digest comparison.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _run(py_args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *py_args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


def _stub_report(tmp: Path, name: str, *, support=84.0, unsupported=9.0,
                 coverage=71.0, agreement=92.0, fatal=0) -> Path:
    out = tmp / f"{name}.json"
    rc = _run([str(SCRIPTS / "make_stub_report.py"),
               "--model", name, "--out", str(out),
               "--support", str(support), "--unsupported", str(unsupported),
               "--coverage", str(coverage), "--agreement", str(agreement),
               "--fatal", str(fatal)])
    assert rc.returncode == 0, rc.stderr
    return out


class TestStubReport(unittest.TestCase):
    def test_report_is_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = _stub_report(Path(td), "qwen3-stub")
            rep = json.loads(out.read_text())
            self.assertEqual(rep["report_schema_version"], 1)
            self.assertEqual(rep["model"], "qwen3-stub")
            # matches report-schema.json required keys
            for k in ["report_schema_version", "model", "metrics",
                      "fatal_failures", "inputs", "created_at"]:
                self.assertIn(k, rep)
            for k in ["source_support", "unsupported_claim", "key_point_coverage",
                      "grading_agreement", "duplicate", "schema_validity"]:
                self.assertIn(k, rep["metrics"])


class TestRoutingDecision(unittest.TestCase):
    def _decide(self, tmp: Path, **kw) -> dict:
        a = _stub_report(tmp, "qwen25-arm", support=78.0, unsupported=15.0,
                         coverage=62.0, agreement=88.0)
        b = _stub_report(tmp, "qwen3-arm", **kw)
        out = tmp / "decision.json"
        rc = _run([str(SCRIPTS / "decide_routing.py"),
                   "--qwen25-report", str(a), "--qwen3-report", str(b),
                   "--schema", str(ROOT / "docs" / "routing-decision.schema.json"),
                   "--out", str(out)])
        self.assertEqual(rc.returncode, 0, rc.stderr)
        return json.loads(out.read_text())

    def test_qwen3_selected_when_gains_met(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = self._decide(Path(td), support=84.0, unsupported=9.0,
                             coverage=71.0, agreement=92.0)
            self.assertEqual(d["decision"], "qwen3")
            self.assertEqual(d["threshold_version"], 1)
            self.assertEqual(d["routing_schema_version"], 1)

    def test_fatal_qwen3_blocks_qwen3(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = self._decide(Path(td), support=84.0, unsupported=9.0,
                             coverage=71.0, agreement=92.0, fatal=2)
            self.assertEqual(d["decision"], "qwen2.5")
            self.assertEqual(d["metrics"]["fatal_qwen3"], 2)

    def test_sub_2pp_support_gain_blocks_qwen3(self) -> None:
        # support_gain = 79 - 78 = 1 < 2 -> qwen2.5
        with tempfile.TemporaryDirectory() as td:
            d = self._decide(Path(td), support=79.0, unsupported=9.0,
                             coverage=71.0, agreement=92.0)
            self.assertEqual(d["decision"], "qwen2.5")

    def test_coverage_or_agreement_gain_alternative(self) -> None:
        # coverage_gain = 0 but agreement_gain = 92-88 = 4 >= 2 -> qwen3
        with tempfile.TemporaryDirectory() as td:
            d = self._decide(Path(td), support=84.0, unsupported=9.0,
                             coverage=62.0, agreement=92.0)
            self.assertEqual(d["decision"], "qwen3")

    def test_unsupported_reduction_sub_2pp_blocks(self) -> None:
        # unsupported_reduction = 15 - 14 = 1 < 2 -> qwen2.5
        with tempfile.TemporaryDirectory() as td:
            d = self._decide(Path(td), support=84.0, unsupported=14.0,
                             coverage=71.0, agreement=92.0)
            self.assertEqual(d["decision"], "qwen2.5")


class TestDecisionValidation(unittest.TestCase):
    def test_tampered_report_flips_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            a = _stub_report(tmp, "qwen25-arm", support=78.0, unsupported=15.0,
                             coverage=62.0, agreement=88.0)
            b = _stub_report(tmp, "qwen3-arm", support=84.0, unsupported=9.0,
                             coverage=71.0, agreement=92.0)
            out = tmp / "decision.json"
            _run([str(SCRIPTS / "decide_routing.py"),
                  "--qwen25-report", str(a), "--qwen3-report", str(b),
                  "--schema", str(ROOT / "docs" / "routing-decision.schema.json"),
                  "--out", str(out)])
            # tamper: flip qwen3 coverage up in the SOURCE report
            rep = json.loads(b.read_text())
            rep["metrics"]["key_point_coverage"] = 99.0
            b.write_text(json.dumps(rep))
            rc = _run([str(SCRIPTS / "validate_routing_decision.py"), str(out)])
            self.assertNotEqual(rc.returncode, 0)
            self.assertIn("DIGEST_MISMATCH", rc.stderr)

    def test_tampered_decision_flips_decision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            a = _stub_report(tmp, "qwen25-arm", support=78.0, unsupported=15.0,
                             coverage=62.0, agreement=88.0)
            b = _stub_report(tmp, "qwen3-arm", support=84.0, unsupported=9.0,
                             coverage=71.0, agreement=92.0)
            out = tmp / "decision.json"
            _run([str(SCRIPTS / "decide_routing.py"),
                  "--qwen25-report", str(a), "--qwen3-report", str(b),
                  "--schema", str(ROOT / "docs" / "routing-decision.schema.json"),
                  "--out", str(out)])
            # tamper: hand-edit the decision
            dec = json.loads(out.read_text())
            dec["decision"] = "qwen2.5"
            out.write_text(json.dumps(dec))
            rc = _run([str(SCRIPTS / "validate_routing_decision.py"), str(out)])
            self.assertNotEqual(rc.returncode, 0)
            self.assertIn("DECISION_MISMATCH", rc.stderr)


class TestLogicalDigests(unittest.TestCase):
    def _descriptor(self, port: int) -> dict:
        return {
            "descriptor_schema_version": 1,
            "executable": "/usr/bin/python",
            "argv": ["-m", "vllm", "--port", str(port)],
            "cwd": "/persistent/models",
            "checkpoint_path": "/persistent/models/Qwen3-32B-AWQ",
            "checkpoint_revision": "a" * 64,
            "env": {"HF_HUB_OFFLINE": "1"},
            "port": port,
            "served_model_id": "Qwen3-32B-AWQ",
            "launcher_method": "manual",
            "captured_at": "2026-01-01T00:00:00+00:00",
        }

    def test_identical_descriptors_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "before.json").write_text(json.dumps(self._descriptor(8002)))
            # captured_at differs -> logically identical
            after = self._descriptor(8002)
            after["captured_at"] = "2026-01-02T00:00:00+00:00"
            (tmp / "after.json").write_text(json.dumps(after))
            rc = _run([str(SCRIPTS / "compare_logical_digests.py"),
                       "--before", str(tmp / "before.json"),
                       "--after", str(tmp / "after.json")])
            self.assertEqual(rc.returncode, 0, rc.stderr)

    def test_port_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "before.json").write_text(json.dumps(self._descriptor(8002)))
            (tmp / "after.json").write_text(json.dumps(self._descriptor(8003)))
            rc = _run([str(SCRIPTS / "compare_logical_digests.py"),
                       "--before", str(tmp / "before.json"),
                       "--after", str(tmp / "after.json")])
            self.assertNotEqual(rc.returncode, 0)
            self.assertIn("FIELD_DIFF port", rc.stderr)


class TestEndToEndStubEval(unittest.TestCase):
    def test_run_model_eval_stub_all(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "eval"
            rc = subprocess.run(
                ["bash", str(SCRIPTS / "run_model_eval.sh"), "--all", "--mode",
                 "stub", "--out-dir", str(out_dir)],
                capture_output=True, text=True, timeout=180)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            self.assertTrue((out_dir / "routing-decision.json").exists())
            self.assertTrue((out_dir / "qwen2.5-vs-qwen3.md").exists())
            self.assertTrue((out_dir / "qwen2.5-vs-qwen3.json").exists())
            for arm in ("qwen25", "qwen3-nonthinking", "qwen3-thinking"):
                self.assertTrue((out_dir / "runs" / f"{arm}.raw.json").exists())
            # validate passes
            rc2 = _run([str(SCRIPTS / "validate_routing_decision.py"),
                        str(out_dir / "routing-decision.json")])
            self.assertEqual(rc2.returncode, 0, rc2.stderr)
            # decision is qwen3 for the stub gains
            dec = json.loads((out_dir / "routing-decision.json").read_text())
            self.assertEqual(dec["decision"], "qwen3")


if __name__ == "__main__":
    unittest.main()
