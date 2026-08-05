from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.corpus_manager import verify_signature  # noqa: E402
from corpus.legacy_recovery.legacy_bucket_classifier import classify_raw_line  # noqa: E402
from corpus.legacy_recovery.legacy_failure_clusterer import build_failure_taxonomy  # noqa: E402
from corpus.legacy_recovery.legacy_parse_recover import recover_json_line  # noqa: E402
from corpus.legacy_recovery.legacy_replay_planner import build_replay_plan  # noqa: E402
from corpus.legacy_recovery.legacy_scan import scan_legacy_roots  # noqa: E402
from corpus.legacy_recovery.legacy_trace_promoter import (  # noqa: E402
    FreshVerifierResult,
    promote_replayed_trace,
)
from corpus.legacy_recovery.programbench_priority_model import build_priority_model  # noqa: E402


def _legacy_row() -> dict:
    return {
        "conversations": [
            {
                "from": "human",
                "value": "Implement tool kyoh86__richgo.313114f for /workspace/executable argv[0] output.",
            },
            {"from": "gpt", "value": '```bash\nexec -a "$0" richgo "$@"\n```'},
        ],
        "metadata": {
            "slug": "kyoh86__richgo.313114f",
            "test_id": "tests.test_color.test_force_color",
            "verdict": "fail",
            "eval_json": "T:/runs/richgo.eval.json",
            "gate_result_path": "T:/runs/gate_result.json",
        },
    }


def test_parse_recover_accepts_wrapped_json_object():
    row, err = recover_json_line("noise " + json.dumps(_legacy_row()) + " trailer")
    assert err == ""
    assert row is not None
    assert row["metadata"]["slug"] == "kyoh86__richgo.313114f"


def test_parse_error_is_unrecoverable_bucket(tmp_path):
    item = classify_raw_line("{bad json", path=tmp_path / "legacy.jsonl", line_number=7)
    assert item.bucket == "unrecoverable"
    assert item.parse_error
    assert "parse_error" in item.failure_classes


def test_reconstructable_verifier_row_detected(tmp_path):
    raw = json.dumps(_legacy_row())
    item = classify_raw_line(raw, path=tmp_path / "legacy.jsonl", line_number=1)
    assert item.bucket == "reconstructable_verifier_row"
    assert item.tool == "kyoh86__richgo.313114f"
    assert item.replayable is True
    assert "argv0_alias_regression" in item.failure_classes


def test_scan_buckets_and_never_marks_training_eligible(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps(_legacy_row()) + "\n{bad json\n", encoding="utf-8")
    report = scan_legacy_roots([path])
    assert report["rows_scanned"] == 2
    assert report["by_bucket"]["reconstructable_verifier_row"] == 1
    assert report["by_bucket"]["unrecoverable"] == 1
    assert report["training_eligible_rows"] == 0


def test_failure_taxonomy_uses_scan_clusters(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps(_legacy_row()) + "\n", encoding="utf-8")
    taxonomy = build_failure_taxonomy(scan_legacy_roots([path]))
    labels = {row["failure_class"] for row in taxonomy["clusters"]}
    assert "argv0_alias_regression" in labels
    assert taxonomy["training_eligible_rows"] == 0


def test_replay_plan_groups_candidates_by_tool(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps(_legacy_row()) + "\n", encoding="utf-8")
    plan = build_replay_plan(scan_legacy_roots([path]))
    assert plan["replay_candidate_count"] == 1
    assert plan["tools"][0]["tool"] == "kyoh86__richgo.313114f"
    assert plan["tools"][0]["training_eligible"] is False


def test_priority_model_can_rank_from_weak_legacy_evidence(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps(_legacy_row()) + "\n", encoding="utf-8")
    model = build_priority_model(scan_legacy_roots([path]))
    assert model["tools"][0]["tool"] == "kyoh86__richgo.313114f"
    assert model["tools"][0]["training_eligible"] is False


def test_promoter_refuses_without_fresh_verifier(tmp_path):
    item = classify_raw_line(
        json.dumps(_legacy_row()), path=tmp_path / "legacy.jsonl", line_number=1
    )
    verifier = FreshVerifierResult(
        verifier_command="",
        verifier_result="pass",
        failure_class="argv0_alias_regression",
        repair_outcome="pass",
        license_provenance="MIT",
    )
    with pytest.raises(ValueError):
        promote_replayed_trace(
            item.to_dict(), verifier, output_jsonl=tmp_path / "out.jsonl", language="go"
        )


def test_promoter_writes_new_signed_recovered_row_not_mutating_legacy(tmp_path):
    item = classify_raw_line(
        json.dumps(_legacy_row()), path=tmp_path / "legacy.jsonl", line_number=1
    )
    verifier = FreshVerifierResult(
        verifier_command="programbench eval",
        verifier_result="pass",
        failure_class="argv0_alias_regression",
        repair_outcome="pass",
        license_provenance="MIT",
        verifier_artifact="T:/runs/gate_result.json",
    )
    output = tmp_path / "corpus" / "recovered.jsonl"
    record = promote_replayed_trace(item.to_dict(), verifier, output_jsonl=output, language="go")

    assert output.exists()
    assert record["record_status"] == "active_training_eligible"
    assert record["training_eligible"] is True
    assert record["source_kind"] == "legacy_replay_recovered"
    assert record["recovered_from"]["legacy_row_hash"] == item.legacy_row_hash
    assert verify_signature(record) is True
