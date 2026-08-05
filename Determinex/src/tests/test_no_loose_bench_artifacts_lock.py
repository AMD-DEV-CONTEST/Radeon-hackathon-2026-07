from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from verified_task.reconcile_benchmark_artifacts import reconcile_roots  # noqa: E402


def test_reconciler_passes_clean_gated_eval_tree(tmp_path):
    run = tmp_path / "run" / "tool__repo.hash"
    run.mkdir(parents=True)
    (tmp_path / "run" / "manifest.json").write_text(
        json.dumps({"items": [{"slug": "tool__repo.hash"}]}), encoding="utf-8"
    )
    (tmp_path / "run" / "gate_result.json").write_text(
        json.dumps({"decision": "reject"}), encoding="utf-8"
    )
    (run / "tool__repo.hash.eval.json").write_text(
        json.dumps({"test_results": []}), encoding="utf-8"
    )

    report = reconcile_roots([tmp_path])

    assert report.eval_json_count == 1
    assert report.issue_count == 0


def test_reconciler_flags_eval_without_status(tmp_path):
    run = tmp_path / "run" / "tool__repo.hash"
    run.mkdir(parents=True)
    (run / "tool__repo.hash.eval.json").write_text(
        json.dumps({"test_results": []}), encoding="utf-8"
    )

    report = reconcile_roots([tmp_path])

    assert report.issue_count == 1
    assert report.issues[0]["kind"] == "eval_without_status"


def test_reconciler_flags_orphan_log(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "task.err.log").write_text("boom", encoding="utf-8")

    report = reconcile_roots([tmp_path])

    assert any(issue["kind"] == "orphan_log" for issue in report.issues)


def test_reconciler_flags_running_shard_in_active_manifest(tmp_path):
    active = tmp_path / "HETZNER_ACTIVE_MANIFEST.json"
    active.write_text(
        json.dumps({"shards": {"demo": {"state": "remote_running"}}}), encoding="utf-8"
    )

    report = reconcile_roots([tmp_path], active_manifest=active)

    assert any(issue["kind"] == "shard_still_running" for issue in report.issues)


def test_reconciler_counts_corpus_trace_statuses(tmp_path):
    trace = tmp_path / "corpus" / "rows.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text(
        json.dumps(
            {
                "record_status": "active_training_eligible",
                "training_eligible": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = reconcile_roots([tmp_path])

    assert report.corpus_trace_count == 1
    assert report.issue_count == 0
