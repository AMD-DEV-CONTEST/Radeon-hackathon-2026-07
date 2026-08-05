from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.corpus_manager import verify_signature  # noqa: E402
from corpus.legacy_recovery.legacy_bucket_classifier import classify_raw_line  # noqa: E402
from corpus.legacy_recovery.legacy_candidate_selector import select_candidates  # noqa: E402
from corpus.legacy_recovery.legacy_chunk_runner import run_chunk  # noqa: E402
from corpus.legacy_recovery.legacy_promotion_budget import PromotionBudget  # noqa: E402
from corpus.legacy_recovery.legacy_taxonomy_stability import build_stability_report  # noqa: E402
from corpus.legacy_recovery.legacy_trace_promoter import (  # noqa: E402
    FreshVerifierResult,
    promote_replayed_trace,
)


def _row(tool: str = "sqlite__sqlite.839433d", test_id: str = "tests.test_sql.test_select") -> dict:
    return {
        "conversations": [
            {
                "from": "human",
                "value": f"Implement {tool} for /workspace/executable stdout date timestamp behavior.",
            },
            {"from": "gpt", "value": "fresh verifier candidate"},
        ],
        "metadata": {
            "slug": tool,
            "test_id": test_id,
            "verdict": "fail",
            "eval_json": f"T:/runs/{tool}.eval.json",
            "gate_result_path": "T:/runs/gate_result.json",
        },
    }


def _item(
    tool: str = "sqlite__sqlite.839433d", test_id: str = "tests.test_sql.test_select"
) -> dict:
    return classify_raw_line(
        json.dumps(_row(tool, test_id)), path=Path("legacy.jsonl"), line_number=1
    ).to_dict()


def _fresh() -> FreshVerifierResult:
    return FreshVerifierResult(
        verifier_command="programbench eval",
        verifier_result="pass",
        failure_class="stdout_stderr_mismatch",
        repair_outcome="pass",
        license_provenance="MIT",
        verifier_artifact="T:/verified/gate_result.json",
    )


def test_promotion_budget_limits_scan_tool_and_duplicate_cluster():
    candidates = [
        _item("sqlite__sqlite.839433d", "tests.a"),
        _item("sqlite__sqlite.839433d", "tests.b"),
        _item("sqlite__sqlite.839433d", "tests.c"),
        _item("duckdb__duckdb.bdb65ec", "tests.d"),
        _item("duckdb__duckdb.bdb65ec", "tests.e"),
    ]
    result = PromotionBudget(max_attempts_per_scan=10, max_per_tool=2, max_per_cluster=1).select(
        candidates
    )

    assert result["selected_count"] == 2
    assert result["rejected_count"] == 3
    assert {row["promotion_reject_reason"] for row in result["rejected"]} >= {
        "duplicate_cluster_budget_exhausted",
    }


def test_promotion_budget_caps_total_scan_attempts():
    candidates = [
        _item("sqlite__sqlite.839433d", "tests.a"),
        _item("duckdb__duckdb.bdb65ec", "tests.b"),
        _item("sharkdp__fd.40d8eb3", "tests.c"),
    ]
    result = PromotionBudget(max_attempts_per_scan=2, max_per_tool=10, max_per_cluster=10).select(
        candidates
    )

    assert result["selected_count"] == 2
    assert result["rejected"][0]["promotion_reject_reason"] == "scan_budget_exhausted"


def test_replay_promotion_requires_fresh_verifier_artifact(tmp_path):
    verifier = FreshVerifierResult(
        verifier_command="programbench eval",
        verifier_result="pass",
        failure_class="stdout_stderr_mismatch",
        repair_outcome="pass",
        license_provenance="MIT",
    )
    with pytest.raises(ValueError):
        promote_replayed_trace(
            _item(), verifier, output_jsonl=tmp_path / "rows.jsonl", language="c"
        )


def test_replay_promotion_writes_new_signed_training_row_and_preserves_legacy(tmp_path):
    legacy_path = tmp_path / "legacy.jsonl"
    raw = json.dumps(_row())
    legacy_path.write_text(raw + "\n", encoding="utf-8")
    legacy_before = legacy_path.read_text(encoding="utf-8")
    item = classify_raw_line(raw, path=legacy_path, line_number=1).to_dict()
    output = tmp_path / "recovered" / "rows.jsonl"

    record = promote_replayed_trace(item, _fresh(), output_jsonl=output, language="c")

    assert legacy_path.read_text(encoding="utf-8") == legacy_before
    assert record["record_status"] == "active_training_eligible"
    assert record["training_eligible"] is True
    assert record["source_kind"] == "legacy_replay_recovered"
    assert record["recovered_from"]["legacy_row_hash"] == item["legacy_row_hash"]
    assert record["verifier_artifact"] == "T:/verified/gate_result.json"
    assert verify_signature(record) is True


def test_chunk_runner_writes_named_artifact(tmp_path):
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        json.dumps(_row("sqlite__sqlite.839433d", "tests.a"))
        + "\n"
        + json.dumps(_row("duckdb__duckdb.bdb65ec", "tests.b"))
        + "\n",
        encoding="utf-8",
    )
    report = run_chunk([legacy], rows=2, label="002", output_dir=tmp_path / "evidence")

    out = tmp_path / "evidence" / "legacy_recovery_scan_002.json"
    assert out.exists()
    assert report["rows_scanned"] == 2
    assert report["replay_candidate_count"] == 2
    assert report["promotion_successes"] == 0
    assert report["training_eligible_rows_created"] == 0


def test_taxonomy_stability_compares_chunks(tmp_path):
    c5 = {
        "label": "005k",
        "rows_scanned": 10,
        "bucket_counts": {"reconstructable_verifier_row": 9, "unrecoverable": 1},
        "top_failure_clusters": [{"failure_class": "stdout_stderr_mismatch", "count": 4}],
        "top_replay_candidates": [{"tool": "sqlite__sqlite.839433d"}],
    }
    c25 = {
        "label": "025k",
        "rows_scanned": 20,
        "bucket_counts": {"reconstructable_verifier_row": 18, "unrecoverable": 2},
        "top_failure_clusters": [
            {"failure_class": "stdout_stderr_mismatch", "count": 8},
            {"failure_class": "argv0_alias_regression", "count": 2},
        ],
        "top_replay_candidates": [
            {"tool": "sqlite__sqlite.839433d"},
            {"tool": "sharkdp__fd.40d8eb3"},
        ],
    }
    p5 = tmp_path / "legacy_recovery_scan_005k.json"
    p25 = tmp_path / "legacy_recovery_scan_025k.json"
    p5.write_text(json.dumps(c5), encoding="utf-8")
    p25.write_text(json.dumps(c25), encoding="utf-8")

    report = build_stability_report([p5, p25])

    assert report["chunks"][0]["reconstructable_rate"] == 0.9
    assert report["class_stability"]["new_classes_by_chunk"]["025k"] == ["argv0_alias_regression"]


def test_candidate_selector_enforces_budget_and_diversity_shape():
    artifact = {
        "top_replay_candidates": [
            {
                "tool": "sqlite__sqlite.839433d",
                "candidate_rows": 10,
                "top_failure_classes": {"stdout_stderr_mismatch": 5},
            },
            {
                "tool": "sharkdp__fd.40d8eb3",
                "candidate_rows": 10,
                "top_failure_classes": {"path_env_dependency": 5},
            },
            {
                "tool": "junegunn__fzf.b56d614",
                "candidate_rows": 10,
                "top_failure_classes": {"exit_code_mismatch": 5},
            },
            {
                "tool": "ariga__atlas.6d81150",
                "candidate_rows": 10,
                "top_failure_classes": {"argv0_alias_regression": 5},
            },
            {
                "tool": "antonmedv__fx.86d0d34",
                "candidate_rows": 10,
                "top_failure_classes": {"uncategorized": 5},
            },
        ]
    }

    selected = select_candidates(artifact)

    assert selected["selected_count"] == 5
    assert selected["diversity"]["distinct_tools"] == 5
    assert selected["diversity"]["distinct_failure_classes"] == 5
    assert all(row["requires_fresh_verifier"] for row in selected["selected"])
