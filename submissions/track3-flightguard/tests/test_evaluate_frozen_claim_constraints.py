from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evaluate_frozen_claim_constraints.py"
SPEC = importlib.util.spec_from_file_location("frozen_claim_constraints", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


EXPECTED_CASES = {
    "radeon_fixed_r5_scaling": (
        "submission/evidence/radeon-formal-scaling.json",
        "98d9b331907f9968ae65054c6f9d840dc0440eb9209c14e955dc628df736f072",
        "ACCEPT",
    ),
    "v4_repair_claim": (
        "submission/evidence/v4-summary.json",
        "4ebab98a9b9c3b134548ef646c30aaafbd7d6ddeaa8a0485b667ee8054f80f8b",
        "REJECT",
    ),
    "v5_incremental_capability_claim": (
        "submission/evidence/v5-summary.json",
        "d546a620931fc3afb2c074d749e1fe017ba6c4dcdf2d05b570855a913e83b034",
        "REJECT",
    ),
    "v6_observer_admission_claim": (
        "submission/evidence/v6-checkpoint-30.json",
        "905925dedc62a41a8b4c35ace8b1c5a1bd1d97c9cb4d43a5f513f3827cf0a678",
        "REJECT",
    ),
}


def test_corpus_paths_hashes_labels_and_scientific_constraints_are_frozen() -> None:
    assert len(MODULE.CASE_CORPUS) == 4
    actual = {
        case.case_id: (
            case.relative_path,
            case.expected_sha256,
            MODULE.EXPECTED_LABELS[case.case_id],
        )
        for case in MODULE.CASE_CORPUS
    }
    assert actual == EXPECTED_CASES
    assert set(MODULE.EXPECTED_LABELS) == set(EXPECTED_CASES)
    by_id = {case.case_id: case for case in MODULE.CASE_CORPUS}
    assert any(c.field.endswith("speedup_vs_32_envs") and c.operator == "ge" for c in by_id["radeon_fixed_r5_scaling"].constraints)
    assert sum(c.field.endswith("coefficient_of_variation") for c in by_id["radeon_fixed_r5_scaling"].constraints) == 4
    assert {c.field for c in by_id["v4_repair_claim"].constraints} == {
        "capability_effect.patch_vs_action_only_failure_reduction_fraction",
        "integrity.checks.patch_not_worse_than_raw_or_calibrated",
    }
    v5_fields = {c.field for c in by_id["v5_incremental_capability_claim"].constraints}
    assert "metrics.CausalIMUPatch.fault.mission_success_count" in v5_fields
    assert sum(field.endswith("all_operational_legacy_fields_raw_bit_exact") for field in v5_fields) == 3
    assert by_id["v6_observer_admission_claim"].constraints == (
        MODULE.Constraint("admitted_lane_count", "ge", 9),
    )


def test_decision_function_has_no_expected_label_or_corpus_dependency() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    target = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "evaluate_constraints"
    )
    names = {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}
    strings = {node.value for node in ast.walk(target) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "expected_label" not in names
    assert "CASE_CORPUS" not in names
    assert "expected_label" not in strings
    assert [argument.arg for argument in target.args.args] == ["artifact", "constraints"]


def test_run_benchmark_decision_loop_does_not_read_labels() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_benchmark"
    )
    decision_loop = next(
        node
        for node in target.body
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "case"
    )
    names = {node.id for node in ast.walk(decision_loop) if isinstance(node, ast.Name)}
    attributes = {
        node.attr for node in ast.walk(decision_loop) if isinstance(node, ast.Attribute)
    }
    assert "EXPECTED_LABELS" not in names
    assert "expected_label" not in attributes


def test_strict_json_rejects_duplicate_and_nonfinite(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"x":1,"x":2}\n', encoding="utf-8")
    with pytest.raises(MODULE.FrozenClaimError, match="duplicate"):
        MODULE.load_strict_json(duplicate)
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"x":NaN}\n', encoding="utf-8")
    with pytest.raises(MODULE.FrozenClaimError, match="non-finite"):
        MODULE.load_strict_json(nonfinite)


def test_generic_eq_ge_le_and_list_field_paths() -> None:
    artifact = {"flag": True, "number": 3.0, "rows": [{"score": 0.2}]}
    constraints = (
        MODULE.Constraint("flag", "eq", True),
        MODULE.Constraint("number", "ge", 3),
        MODULE.Constraint("rows.0.score", "le", 0.2),
    )
    decision, results = MODULE.evaluate_constraints(artifact, constraints)
    assert decision == "ACCEPT"
    assert all(item["passed"] for item in results)
    rejected, _ = MODULE.evaluate_constraints(
        artifact, (MODULE.Constraint("number", "ge", 4),)
    )
    assert rejected == "REJECT"


def test_verified_frozen_corpus_produces_one_accept_three_rejects() -> None:
    rows = []
    for case in MODULE.CASE_CORPUS:
        payload, actual_sha, _size = MODULE.load_verified_artifact(
            ROOT / case.relative_path, case.expected_sha256
        )
        assert actual_sha == case.expected_sha256
        decision, _results = MODULE.evaluate_constraints(payload, case.constraints)
        rows.append(
            {
                "decision": decision,
                "expected_label": MODULE.EXPECTED_LABELS[case.case_id],
            }
        )
    assert [row["decision"] for row in rows] == ["ACCEPT", "REJECT", "REJECT", "REJECT"]
    metrics = MODULE.score_predictions(rows)
    assert metrics == {
        "true_positive": 1,
        "true_negative": 3,
        "false_positive": 0,
        "false_negative": 0,
        "precision": 1.0,
        "recall": 1.0,
        "specificity": 1.0,
        "accuracy": 1.0,
        "false_accept_count": 0,
        "false_accept_rate": 0.0,
    }


def test_scoring_handles_zero_denominators_without_division_error() -> None:
    metrics = MODULE.score_predictions(
        [{"decision": "REJECT", "expected_label": "REJECT"}]
    )
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["specificity"] == 1.0


def test_source_hash_mismatch_fails_before_output(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    rc = MODULE.cli(
        ["--expected-source-sha256", "0" * 64, "--output", str(output)]
    )
    assert rc != 0
    assert not output.exists()


def test_verified_artifact_hash_and_parse_use_one_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "artifact.json"
    raw = b'{"status":"PASS"}\n'
    artifact.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    original = Path.read_bytes
    reads: list[Path] = []

    def tracked_read_bytes(path: Path) -> bytes:
        reads.append(path.resolve())
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)
    payload, actual, size = MODULE.load_verified_artifact(artifact, expected)
    assert payload == {"status": "PASS"}
    assert actual == expected
    assert size == len(raw)
    assert reads == [artifact.resolve()]


def test_verified_artifact_hash_mismatch_is_fatal(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"status":"PASS"}\n', encoding="utf-8")
    with pytest.raises(MODULE.FrozenClaimError, match="SHA256 mismatch"):
        MODULE.load_verified_artifact(artifact, "0" * 64)


def test_exclusive_output_is_canonical_and_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    payload = {"b": 2, "a": 1}
    MODULE.write_exclusive(output, payload)
    assert output.read_bytes() == b'{"a":1,"b":2}\n'
    assert output.stat().st_mode & 0o777 == 0o444
    with pytest.raises(FileExistsError):
        MODULE.write_exclusive(output, payload)
    assert output.read_bytes() == b'{"a":1,"b":2}\n'


def test_run_benchmark_scope_and_source_binding() -> None:
    source_sha = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    payload = MODULE.run_benchmark(expected_source_sha256=source_sha)
    assert payload["status"] == "PASS"
    assert payload["source"]["sha256"] == source_sha
    assert payload["scope"] == {
        "name": "frozen 4-case synthetic corpus",
        "case_count": 4,
        "simulation_only": True,
        "robot_capability_claim": False,
        "safety_claim": False,
        "general_accuracy_claim": False,
    }
    assert len(payload["decision_latency_ns"]["samples"]) == 4
    assert payload["decision_latency_ns"]["maximum"] >= 0
