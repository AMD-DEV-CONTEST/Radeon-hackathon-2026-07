from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from qa.scripts.capture_vram import parse_metrics
from qa.scripts.check_asset_schema import check as check_asset
from qa.scripts.check_progress_invariants import check as check_progress
from qa.scripts.check_retrieval_phase import check as check_retrieval_phase
from qa.scripts.validate_candidate_plan import validate as validate_plan
from qa.scripts.validate_manifest import validate as validate_manifest
from qa.scripts.summarize_metrics import summarize

ROOT = pathlib.Path(__file__).resolve().parents[1]


def valid_asset() -> dict:
    routes = {
        name: {"eligibility": "eligible"}
        for name in ("private_self", "beginner", "peer", "customer_evaluator", "public")
    }
    routes["customer_evaluator"] = {
        "eligibility": "ineligible",
        "reason": "No professional or client context",
    }
    routes["public"] = {"eligibility": "eligible_after_privacy_approval"}
    return {
        "asset_id": "asset-test",
        "fixture_id": "chair_public_complete",
        "version": "0.1.0",
        "created_utc": "2026-07-24T00:00:00Z",
        "provenance": {
            "source_kind": "adapted_public_research",
            "adapted": True,
            "first_party_testimony": False,
        },
        "context": "A chair trial",
        "goal": "Preserve and share transferable experience",
        "statements": [
            {"text": "The trial lasted about two weeks", "status": "source_fact", "evidence_ref": "fixture:1"},
            {"text": "The fit is personal", "status": "user_judgment", "evidence_ref": "fixture:3"},
        ],
        "routes": routes,
    }


def valid_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "run_group_id": "20260724-baseline-interactive",
        "timestamp_utc": "2026-07-24T00:00:00Z",
        "profile_label": "baseline-v1",
        "git_commit": "a" * 40,
        "hardware": {"gpu": "AMD Radeon PRO W7900", "vram_gib": 48, "local_proof_ref": "r0/summary.txt"},
        "software": {"container": "image@sha256:test", "rocm": "7.2.1", "torch": "2.11", "vllm": "0.23"},
        "model": {"repository": "Qwen/example", "revision": "abc123", "dtype": "bf16", "quantization": "none"},
        "serving": {
            "context_length": 8192,
            "max_output_tokens": 1024,
            "gpu_memory_utilization": 0.9,
            "max_num_seqs": 4,
            "server_args": ["--enable-auto-tool-choice"],
        },
        "workload": {"fixture_set_version": "0.1.0", "workflow_version": "0.1.0", "scenario_type": "interactive"},
        "measurement": {"num_prompts": 10, "warmup_runs": 2, "measured_runs": 10, "concurrency": 1, "temperature": 0},
        "outcomes": {"success_count": 9, "failure_count": 1, "raw_result_ref": "raw/results.json"},
    }


def valid_plan() -> dict:
    return {
        "schema_version": "1.0",
        "candidate_name": "runtime-more-sequences",
        "target_stage": "model-serving",
        "business_reason": "Measure interactive concurrency without changing the task",
        "primary_metric": "request throughput",
        "hypothesis": "A larger sequence budget improves throughput",
        "quality_floors": ["no Critical or High regression"],
        "frozen_manifest_ref": "baseline/manifest.json",
        "declared_changes": [
            {"path": "serving.max_num_seqs", "baseline": 4, "candidate": 8, "reason": "candidate under test"}
        ],
        "side_effects": "May increase peak VRAM",
        "rollback": "restore max_num_seqs=4",
        "approved_before_measurement": "2026-07-24T00:00:00Z",
    }


def valid_retrieval_trace() -> dict:
    return {
        "schema_version": "0.1.0",
        "asset_id": "asset-current",
        "events": [
            {
                "sequence": 1,
                "event_type": "current_source_retrieval",
                "scope": "current_asset",
                "related_asset_id": "asset-current",
            },
            {
                "sequence": 2,
                "event_type": "knowledge_card_ready",
                "knowledge_card_version": "v4",
                "knowledge_card_hash": "sha256:current-v4",
                "milestone_state": "CONFIRMED",
                "explicit_user_acceptance": True,
            },
            {
                "sequence": 3,
                "event_type": "relation_candidate_search",
                "scope": "cross_asset_summary",
                "related_asset_id": "asset-prior",
                "detail_included": False,
            },
            {
                "sequence": 4,
                "event_type": "relation_confirmation",
                "relation_id": "relation-1",
                "related_asset_id": "asset-prior",
                "confirmed": True,
            },
            {
                "sequence": 5,
                "event_type": "relation_detail_retrieval",
                "scope": "cross_asset_detail",
                "relation_id": "relation-1",
                "related_asset_id": "asset-prior",
                "knowledge_card_version": "v4",
                "provenance_refs": ["asset-prior:statement-2"],
                "mutated_current_statements": False,
                "current_statements_hash_before": "sha256:statements-v4",
                "current_statements_hash_after": "sha256:statements-v4",
            },
        ],
    }


class PublicContractTests(unittest.TestCase):
    def test_fixture_inventory_passes(self):
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts" / "check_fixture_inventory.py")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_valid_asset_passes(self):
        expected = json.loads((ROOT / "expected" / "chair_public_complete.expected.json").read_text())
        self.assertEqual(check_asset(valid_asset(), expected), [])

    def test_source_fact_without_evidence_is_critical(self):
        asset = valid_asset()
        asset["statements"][0].pop("evidence_ref")
        findings = check_asset(asset)
        self.assertTrue(any(severity == "CRITICAL" and ac == "AC-03" for severity, ac, _ in findings))

    def test_progress_rejects_fake_percentage_and_eta(self):
        findings = check_progress({"percent": 90, "percent_basis": "milestones_done/milestones_total", "milestones_done": 1, "milestones_total": 5, "eta_seconds": 30})
        self.assertGreaterEqual(len(findings), 2)

    def test_progress_accepts_state_derived_feedback(self):
        event = {
            "percent": 40,
            "percent_basis": "milestones_done/milestones_total",
            "milestones_done": 2,
            "milestones_total": 5,
            "eta_seconds": 120,
            "eta_basis": "same fixture/workflow profile",
            "eta_history_sample_size": 5,
        }
        self.assertEqual(check_progress(event), [])

    def test_retrieval_phase_accepts_current_then_confirmed_history(self):
        self.assertEqual(check_retrieval_phase(valid_retrieval_trace()), [])

    def test_retrieval_phase_accepts_visible_no_match_after_card_ready(self):
        trace = valid_retrieval_trace()
        trace["events"] = trace["events"][:2] + [
            {"sequence": 3, "event_type": "relation_no_match"}
        ]
        self.assertEqual(check_retrieval_phase(trace), [])

    def test_retrieval_phase_accepts_declined_candidate_without_detail(self):
        trace = valid_retrieval_trace()
        trace["events"] = trace["events"][:4]
        trace["events"][-1]["confirmed"] = False
        self.assertEqual(check_retrieval_phase(trace), [])

    def test_retrieval_phase_rejects_cross_asset_search_before_card_ready(self):
        trace = valid_retrieval_trace()
        trace["events"].pop(1)
        findings = check_retrieval_phase(trace)
        self.assertTrue(any("before Knowledge Card readiness" in item[2] for item in findings))

    def test_retrieval_phase_rejects_detail_before_relation_confirmation(self):
        trace = valid_retrieval_trace()
        trace["events"].pop(3)
        findings = check_retrieval_phase(trace)
        self.assertTrue(any("not limited to a user-confirmed relation" in item[2] for item in findings))

    def test_retrieval_phase_rejects_historical_fact_contamination(self):
        trace = valid_retrieval_trace()
        trace["events"][-1]["mutated_current_statements"] = True
        findings = check_retrieval_phase(trace)
        self.assertTrue(any("silently mutated current statements" in item[2] for item in findings))

    def test_retrieval_phase_rejects_current_statement_hash_drift(self):
        trace = valid_retrieval_trace()
        trace["events"][-1]["current_statements_hash_after"] = "sha256:changed"
        findings = check_retrieval_phase(trace)
        self.assertTrue(any("snapshot changed" in item[2] for item in findings))

    def test_retrieval_phase_invalidates_gate_after_current_card_change(self):
        trace = valid_retrieval_trace()
        trace["events"].insert(2, {"sequence": 3, "event_type": "current_card_changed"})
        for index, event in enumerate(trace["events"], start=1):
            event["sequence"] = index
        findings = check_retrieval_phase(trace)
        self.assertTrue(any("before Knowledge Card readiness" in item[2] for item in findings))

    def test_manifest_is_complete_and_counts_match(self):
        self.assertEqual(validate_manifest(valid_manifest()), [])
        manifest = valid_manifest()
        manifest["outcomes"]["failure_count"] = 0
        self.assertIn("success_count + failure_count must equal measured_runs", validate_manifest(manifest))

    def test_candidate_plan_has_no_prefilled_threshold(self):
        self.assertEqual(validate_plan(valid_plan()), [])
        plan = valid_plan()
        plan["primary_metric"] = "<choose after results>"
        self.assertIn("primary_metric", validate_plan(plan))

    def test_manifest_comparison_accepts_only_declared_change(self):
        plan = valid_plan()
        baseline = valid_manifest()
        candidate = copy.deepcopy(baseline)
        candidate["profile_label"] = "candidate-runtime-more-sequences"
        candidate["serving"]["max_num_seqs"] = 8
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for name, data in (("plan", plan), ("base", baseline), ("candidate", candidate)):
                path = pathlib.Path(temp) / f"{name}.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                paths.append(str(path))
            completed = subprocess.run(
                ["python3", str(ROOT / "scripts" / "compare_manifests.py"), *paths],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_manifest_comparison_rejects_undeclared_drift(self):
        plan = valid_plan()
        baseline = valid_manifest()
        candidate = copy.deepcopy(baseline)
        candidate["serving"]["max_num_seqs"] = 8
        candidate["model"]["dtype"] = "fp16"
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for name, data in (("plan", plan), ("base", baseline), ("candidate", candidate)):
                path = pathlib.Path(temp) / f"{name}.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                paths.append(str(path))
            completed = subprocess.run(
                ["python3", str(ROOT / "scripts" / "compare_manifests.py"), *paths],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("undeclared frozen-condition drift", completed.stdout)

    def test_amd_smi_normalizer(self):
        sample = {"gpu0": {"vram": {"used_bytes": 10 * 1024 * 1024}, "usage": {"gfx_activity": 73}}}
        self.assertEqual(parse_metrics(sample), (10.0, 73.0))

    def test_metric_summary_keeps_failures_and_statistics(self):
        records = [
            {"run_id": "r1", "scenario_type": "interactive", "success": True, "terminal_state": "complete", "ttft_ms": 100},
            {"run_id": "r2", "scenario_type": "interactive", "success": False, "terminal_state": "timeout", "ttft_ms": 200},
        ]
        summary = summarize(records)
        self.assertEqual(summary["failure_count"], 1)
        self.assertEqual(summary["failure_rate"], 0.5)
        self.assertEqual(summary["metrics"]["ttft_ms"]["median"], 150)

    def test_metric_summary_rejects_mixed_scenarios(self):
        records = [
            {"run_id": "r1", "scenario_type": "interactive", "success": True, "terminal_state": "complete"},
            {"run_id": "r2", "scenario_type": "stress", "success": True, "terminal_state": "complete"},
        ]
        with self.assertRaises(ValueError):
            summarize(records)

    def test_artifact_gate_fails_closed_without_artifact(self):
        completed = subprocess.run(
            ["bash", str(ROOT / "gates" / "pr_gate.sh"), "--mode", "artifact"],
            cwd=ROOT.parent,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("requires --asset", completed.stdout)

    def test_pr_metadata_rejects_empty_body(self):
        env = dict(os.environ)
        env["PR_BODY"] = ""
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts" / "check_pr_metadata.py")],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_pr_metadata_accepts_complete_public_mapping(self):
        env = dict(os.environ)
        env["PR_BODY"] = """AC-25\nL1 milestone: cross-cutting\nL2 capability: Evidence discipline\nFixture: chair_public_complete\nPublic evidence:\n- Test/fixture result: qa contract gate PASS\n"""
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts" / "check_pr_metadata.py")],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_pr_metadata_accepts_lean_review_essentials(self):
        env = dict(os.environ)
        env["PR_BODY"] = """## Outcome
Adds the bounded retry behavior.

- Main behavior/risk changed: timeout recovery only
- Checks run and result: targeted tests PASS
- Known unverified area: W7900 rerun is deferred
- Rollback/revert path: revert this PR
"""
        completed = subprocess.run(
            ["python3", str(ROOT / "scripts" / "check_pr_metadata.py")],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_artifact_gate_accepts_valid_public_evidence(self):
        progress = {
            "percent": 40,
            "percent_basis": "milestones_done/milestones_total",
            "milestones_done": 2,
            "milestones_total": 5,
            "eta_seconds": None,
        }
        with tempfile.TemporaryDirectory() as temp:
            asset_path = pathlib.Path(temp) / "asset.json"
            progress_path = pathlib.Path(temp) / "progress.json"
            asset_path.write_text(json.dumps(valid_asset()), encoding="utf-8")
            progress_path.write_text(json.dumps(progress), encoding="utf-8")
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "gates" / "pr_gate.sh"),
                    "--mode",
                    "artifact",
                    "--asset",
                    str(asset_path),
                    "--fixture-id",
                    "chair_public_complete",
                    "--progress",
                    str(progress_path),
                ],
                cwd=ROOT.parent,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_artifact_gate_accepts_valid_retrieval_trace(self):
        progress = {
            "percent": 80,
            "percent_basis": "milestones_done/milestones_total",
            "milestones_done": 4,
            "milestones_total": 5,
            "eta_seconds": None,
        }
        with tempfile.TemporaryDirectory() as temp:
            asset_path = pathlib.Path(temp) / "asset.json"
            progress_path = pathlib.Path(temp) / "progress.json"
            trace_path = pathlib.Path(temp) / "retrieval.json"
            asset_path.write_text(json.dumps(valid_asset()), encoding="utf-8")
            progress_path.write_text(json.dumps(progress), encoding="utf-8")
            trace_path.write_text(json.dumps(valid_retrieval_trace()), encoding="utf-8")
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "gates" / "pr_gate.sh"),
                    "--mode",
                    "artifact",
                    "--asset",
                    str(asset_path),
                    "--fixture-id",
                    "chair_public_complete",
                    "--progress",
                    str(progress_path),
                    "--retrieval-trace",
                    str(trace_path),
                ],
                cwd=ROOT.parent,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_m4_gate_requires_retrieval_trace(self):
        completed = subprocess.run(
            ["bash", str(ROOT / "gates" / "milestone_gate.sh"), "M4"],
            cwd=ROOT.parent,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("requires --retrieval-trace", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
