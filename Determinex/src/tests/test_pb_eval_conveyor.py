import json
from pathlib import Path

from scripts.pb_eval_conveyor import load_eval_packet, render_handback, render_packet


def write_report(path: Path, rows: list[dict], log: list[str] | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "test_results": rows,
                "log": log or [],
                "warnings": [],
                "solution_branch": "submission",
                "test_branches": [],
                "test_branch_errors": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_strict_report_is_candidate_not_certified(tmp_path: Path) -> None:
    report = tmp_path / "example__tool.abc123.eval.json"
    write_report(
        report,
        [
            {"name": "tests.test_cli.test_help", "branch": "aaa", "status": "passed"},
            {"name": "tests.test_cli.test_run", "branch": "aaa", "status": "passed"},
        ],
    )

    packet = load_eval_packet(report)

    assert packet.slug == "example__tool.abc123"
    assert packet.total == 2
    assert packet.counts["passed"] == 2
    assert packet.verdict == "strict-lock-candidate"
    assert packet.failure_class == "section-5-verification-required"
    assert "Driver parses eval_report directly" in packet.next_actions[0]


def test_collection_error_cascade_is_bounced_before_behavior(tmp_path: Path) -> None:
    report = tmp_path / "tree-sitter__tree-sitter.5e23cca.eval.json"
    rows = [
        {
            "name": "tests.test_loader_advanced_gaps",
            "branch": "40cb72101fde",
            "status": "error",
            "extra": {
                "message": "collection failure",
                "text": "ImportError: cannot import name run_cli",
            },
        },
    ]
    rows.extend(
        {
            "name": f"tests.test_build.test_{i}",
            "branch": "40cb72101fde",
            "status": "not_run",
            "extra": {"message": "not present in JUnit XML"},
        }
        for i in range(60)
    )
    rows.append(
        {
            "name": "tests.test_cli.test_real_behavior",
            "branch": "other",
            "status": "failure",
            "extra": {"message": "AssertionError: wrong output"},
        }
    )
    write_report(report, rows)

    packet = load_eval_packet(report)

    assert packet.verdict == "bounce"
    assert packet.failure_class == "collection-module-wall"
    assert packet.branch_clusters[0].branch == "40cb72101fde"
    assert "module collection wall" in packet.pattern_signatures
    assert "branch-local error cascade to not_run" in packet.pattern_signatures
    assert "40cb72101fde" in packet.next_actions[0]


def test_rendered_packet_and_handback_are_non_certifying(tmp_path: Path) -> None:
    report = tmp_path / "skeema__skeema.6a76243.eval.json"
    write_report(
        report,
        [
            {
                "name": "eval.tests.test_command_execution_paths.test_diff_attempts_processing",
                "branch": "7c9925b9a694",
                "status": "failure",
                "extra": {"message": "AssertionError: database dry-run produced no output"},
            },
            {
                "name": "eval.tests.test_command_execution_paths.test_ok",
                "branch": "7c9925b9a694",
                "status": "passed",
            },
        ],
    )
    packet = load_eval_packet(report)
    packet_text = render_packet(
        [packet], batch_id="TEST-BATCH", remote_pid="123", remote_log="/tmp/log"
    )
    handback_text = render_handback(tmp_path / "packet.md", [packet], "TEST-BATCH")

    assert "driver Section 5 only" in packet_text
    assert "database/dry-run behavior" in packet_text
    assert "lock_claim: none by Codex" in handback_text
    assert "training_eligible stays false" in handback_text


def test_behavioral_failure_with_directory_text_is_not_image_plumbing(tmp_path: Path) -> None:
    report = tmp_path / "alexpovel__srgn.89f943b.eval.json"
    write_report(
        report,
        [
            {
                "name": "tests.test_harvest.test_cli_stdin_operations",
                "branch": "3007289124ea",
                "status": "failure",
                "extra": {
                    "message": "AssertionError: stdout mismatch for (stdin)",
                    "text": "directory traversal prose should not imply executable plumbing",
                },
            },
            {
                "name": "tests.test_help.test_usage",
                "branch": "86582e2e370b",
                "status": "failure",
                "extra": {"message": "AssertionError: usage line mismatch"},
            },
        ],
    )

    packet = load_eval_packet(report)

    assert packet.verdict == "improved, NOT lock-eligible"
    assert packet.failure_class == "targeted-behavioral"
    assert "image/executable plumbing" not in packet.pattern_signatures
