import json
from pathlib import Path

from scripts.pb_best_state_index import build_index
from scripts.pb_tool_brief import brief


def write_eval(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"test_results": rows, "log": [], "warnings": []}),
        encoding="utf-8",
    )


def test_best_state_prefers_passed_then_failed_not_run(tmp_path: Path, monkeypatch) -> None:
    eval_index = tmp_path / "eval_index.json"
    eval_index.write_text(
        json.dumps(
            [
                {"slug": "owner__tool.abc123", "status": "board_cache_only"},
                {"slug": "alias", "canonical_slug": "owner__tool.abc123"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.pb_best_state_index.EVAL_INDEX", eval_index)

    worse = tmp_path / "old" / "owner__tool.abc123.eval.json"
    better = tmp_path / "new" / "owner__tool.abc123.eval.json"
    write_eval(
        worse,
        [
            {"name": "tests.test_a", "branch": "a", "status": "passed"},
            {"name": "tests.test_b", "branch": "a", "status": "failure"},
        ],
    )
    write_eval(
        better,
        [
            {"name": "tests.test_a", "branch": "a", "status": "passed"},
            {"name": "tests.test_b", "branch": "a", "status": "passed"},
            {"name": "tests.test_c", "branch": "a", "status": "failure"},
        ],
    )
    tarball = tmp_path / "owner__tool.abc123" / "submission.tar.gz"
    tarball.parent.mkdir(parents=True, exist_ok=True)
    tarball.write_bytes(b"fake tarball")

    index = build_index([tmp_path], include_hashes=True)
    row = index["tools"]["owner__tool.abc123"]

    assert index["tool_count"] == 1
    assert row["aliases"] == ["alias"]
    assert row["best_report"].replace("\\", "/").endswith("new/owner__tool.abc123.eval.json")
    assert row["passed"] == 2
    assert row["delta_to_lock"] == 1
    assert row["best_tarball"].replace("\\", "/").endswith("submission.tar.gz")
    assert row["failing_test_ids"] == ["tests.test_c"]


def test_tool_brief_uses_best_state_and_nearest_locked(monkeypatch) -> None:
    index = {
        "tools": {
            "owner__target.abc123": {
                "aliases": [],
                "best_report": "corpus/programbench/results/owner__target.abc123.eval.json",
                "best_tarball": "corpus/programbench/in_progress/target/submission.tar.gz",
                "best_overrides": "corpus/programbench/per_tool_overrides/owner__target.abc123",
                "passed": 9,
                "total": 10,
                "failed": 1,
                "errors": 0,
                "skipped": 0,
                "not_run": 0,
                "delta_to_lock": 1,
                "failing_test_ids": ["tests.test_help"],
                "state_lineage": [
                    {
                        "failure_class": "targeted-behavioral",
                        "pattern_signatures": ["help/usage formatting"],
                    }
                ],
                "eval_index_status": "board_cache_only",
            },
            "owner__locked.def456": {
                "aliases": [],
                "best_report": "corpus/programbench/locked/locked/eval_report.json",
                "best_tarball": "corpus/programbench/locked/locked/submission.tar.gz",
                "best_overrides": "corpus/programbench/per_tool_overrides/owner__locked.def456/Cargo.toml",
                "passed": 10,
                "total": 10,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "not_run": 0,
                "delta_to_lock": 0,
                "failing_test_ids": [],
                "state_lineage": [],
                "eval_index_status": "strict_lock",
            },
        }
    }
    monkeypatch.setattr(
        "scripts.pb_tool_brief.read_text",
        lambda *_args, **_kwargs: "## Pattern X\nhelp/usage formatting\n",
    )
    monkeypatch.setattr(
        "scripts.pb_tool_brief.tail_matching_lines",
        lambda *_args, **_kwargs: ["prior diagnosis line"],
    )

    text = brief("target", index)

    assert "# ProgramBench Tool Brief - owner__target.abc123" in text
    assert "delta_to_lock: `1`" in text
    assert "`tests.test_help`" in text
    assert "Pattern X" in text
    assert "owner__locked.def456" in text
