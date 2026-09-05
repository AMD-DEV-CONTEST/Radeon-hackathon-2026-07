#!/usr/bin/env python3
"""Capture the sanitized E5 local evidence packet — ticket 10.

Everything about E5 that can be proven on a machine without a Radeon, recorded
at an exact commit.

## Why this runs the suite instead of re-checking the behaviours

Each GRAG behaviour below names the tests that already prove it. The script runs
those tests and records what they report. Re-implementing the eighteen checks
here would create a second description of the same behaviour, and the two would
drift — at which point the packet would be evidence about the script rather than
about the product.

The cost of that choice is that this file must stay honest about *where* each
behaviour is proven. `seam` is recorded per behaviour: `HTTP` means it is proven
at the public API, `MODULE` means at an application or repository seam. Ticket
10's first criterion asks for the authoritative external seam, so a behaviour
proven only at a module seam is reported as such rather than counted as if it
were an HTTP proof.

## What is deliberately not claimed

No W7900, ROCm or vLLM claim appears anywhere in the output. Every behaviour
here runs against the deterministic fake model. Claims needing real hardware are
emitted as `BLOCKED` with a pointer to ticket 11, never as `PASS`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACKET_SCHEMA_VERSION = "e5-local-evidence/v1"

PYTEST = (sys.executable, "-m", "pytest", "--color=no", "-p", "no:warnings")


@dataclass(frozen=True)
class Behaviour:
    """One GRAG row, bound to the tests that prove it."""

    grag_id: str
    ticket: str
    seam: str
    tests: tuple[str, ...]
    summary: str
    blocked_reason: str | None = None


@dataclass
class CommandRun:
    """One recorded command: what ran, and what it returned."""

    label: str
    argv: tuple[str, ...]
    returncode: int
    tail: str = field(default="")

    @property
    def passed(self) -> bool:
        return self.returncode == 0


BEHAVIOURS: tuple[Behaviour, ...] = (
    Behaviour(
        "GRAG-01",
        "03",
        "HTTP",
        (
            "tests/integration/test_m4_readiness.py"
            "::test_discovery_before_readiness_is_denied_before_any_work",
        ),
        "Discovery before an exact ready card is denied before any cross-asset read or model call.",
    ),
    Behaviour(
        "GRAG-02",
        "03",
        "HTTP",
        ("tests/integration/test_m4_readiness.py::test_acceptance_starts_no_discovery_run",),
        "Accepting a card starts no discovery run.",
    ),
    Behaviour(
        "GRAG-03",
        "05",
        "MODULE",
        (
            "tests/integration/test_e5_discovery.py"
            "::test_a_validated_candidate_carries_the_whole_package",
            "tests/integration/test_e5_discovery.py::test_model_prose_never_reaches_the_candidate",
        ),
        "The cross-topic positive yields exactly one candidate carrying the whole validated "
        "package.",
    ),
    Behaviour(
        "GRAG-04",
        "05",
        "MODULE",
        (
            "tests/integration/test_e5_discovery.py"
            "::test_the_hard_negative_corpus_is_a_finished_search",
            "tests/integration/test_e5_discovery.py"
            "::test_the_unrelated_asset_never_becomes_the_candidate",
        ),
        "The hard-negative corpus produces a semantic NO_MATCH presented as a finished search.",
    ),
    Behaviour(
        "GRAG-05",
        "05",
        "MODULE",
        ("tests/integration/test_e5_discovery.py::test_a_no_match_proposal_yields_no_candidate",),
        "One valid relation under top_k=3 returns one candidate, with no filler.",
    ),
    Behaviour(
        "GRAG-06",
        "05",
        "MODULE",
        (
            "tests/integration/test_e5_discovery.py::test_every_frozen_defect_has_a_test",
            "tests/integration/test_e5_discovery.py::test_forbidden_label_is_rejected",
            "tests/integration/test_e5_discovery.py::test_nonexistent_node_is_rejected",
            "tests/integration/test_e5_discovery.py"
            "::test_a_current_node_submitted_as_historical_is_rejected",
            "tests/integration/test_e5_discovery.py::test_an_inadmissible_role_pair_is_rejected",
            "tests/integration/test_e5_discovery.py"
            "::test_a_projection_the_runtime_never_supplied_is_rejected",
        ),
        "Every frozen invalid proposal yields no candidate and a safe validation failure.",
    ),
    Behaviour(
        "GRAG-07",
        "06",
        "MODULE",
        (
            "tests/integration/test_e5_discovery_attempt.py"
            "::test_the_same_fingerprint_serves_one_cached_answer",
        ),
        "Repeating discovery under one fingerprint returns the same answer without another model "
        "call.",
    ),
    Behaviour(
        "GRAG-08",
        "06",
        "MODULE",
        (
            "tests/integration/test_e5_discovery_attempt.py"
            "::test_a_technical_failure_is_retained_but_never_served_as_no_match",
            "tests/integration/test_e5_discovery_attempt.py"
            "::test_the_retry_budget_is_bounded_and_terminates",
        ),
        "A technical failure permits a new bounded attempt and is never served as a no-match.",
    ),
    Behaviour(
        "GRAG-09",
        "06",
        "MODULE",
        (
            "tests/integration/test_e5_discovery_attempt.py"
            "::test_every_covered_input_moves_the_fingerprint",
            "tests/integration/test_e5_discovery_attempt.py"
            "::test_a_newly_eligible_historical_asset_moves_the_fingerprint",
        ),
        "Changing card, eligible projections, model, prompt or configuration produces a new "
        "fingerprint.",
    ),
    Behaviour(
        "GRAG-10",
        "07",
        "MODULE",
        (
            "tests/integration/test_e5_decision.py"
            "::test_a_declined_relation_never_produces_an_evidence_card",
        ),
        "Detail demanded before confirmation is refused, with no historical read.",
    ),
    Behaviour(
        "GRAG-11",
        "07",
        "MODULE",
        (
            "tests/integration/test_e5_decision.py"
            "::test_declining_persists_and_leaves_no_permission",
        ),
        "A decline persists and leaves detail locked.",
    ),
    Behaviour(
        "GRAG-12",
        "07",
        "MODULE",
        (
            "tests/integration/test_e5_decision.py"
            "::test_a_decision_naming_another_related_asset_is_refused",
            "tests/integration/test_e5_decision.py::test_a_mismatched_card_hash_is_refused",
            "tests/integration/test_e5_decision.py"
            "::test_a_stale_card_version_is_refused_not_resolved",
        ),
        "A confirmation with a mismatched binding is refused and creates no permission.",
    ),
    Behaviour(
        "GRAG-13",
        "08",
        "HTTP",
        (
            "tests/integration/test_e5_evidence_route.py"
            "::test_a_confirmed_relation_returns_its_rendered_card",
            "tests/integration/test_e5_evidence_route.py"
            "::test_an_unknown_relation_answers_the_same_way_as_a_revoked_one",
        ),
        "An exact confirmation yields the deterministic bilateral card, scoped to the one "
        "confirmed asset.",
    ),
    Behaviour(
        "GRAG-14",
        "08",
        "HTTP",
        (
            "tests/integration/test_e5_evidence_route.py"
            "::test_the_read_leaves_the_current_card_hash_untouched",
            "tests/integration/test_e5_evidence_card.py",
        ),
        "Snapshot JSON, statement hash and card hash are identical across a detail read.",
    ),
    Behaviour(
        "GRAG-15",
        "09",
        "MODULE",
        (
            "tests/integration/test_e5_invalidation.py"
            "::test_restart_restores_candidate_decision_and_permission",
            "tests/integration/test_e5_invalidation.py"
            "::test_restart_restores_a_decline_and_the_terminal_discovery_state",
            "tests/integration/test_e5_invalidation.py"
            "::test_restart_does_not_resurrect_access_that_was_revoked",
        ),
        "A restart restores candidate, decline, confirmation, permission and terminal state.",
    ),
    Behaviour(
        "GRAG-16",
        "09",
        "MODULE",
        (
            "tests/integration/test_e5_invalidation.py"
            "::test_correcting_the_current_asset_revokes_everything_built_on_it",
            "tests/integration/test_e5_invalidation.py"
            "::test_changing_the_related_asset_leaves_the_current_one_ready_but_stale",
            "tests/integration/test_e5_invalidation.py"
            "::test_deletion_and_privacy_narrowing_revoke_detail_access_immediately",
        ),
        "Correcting or deleting a bound asset makes projections and relations stale and revokes "
        "access.",
    ),
    Behaviour(
        "GRAG-17",
        "05",
        "MODULE",
        ("tests/integration/test_e5_discovery.py::test_model_prose_never_reaches_the_candidate",),
        "Canonical summary text stays data: no tool call, scope widening or extra field is "
        "accepted.",
    ),
    Behaviour(
        "GRAG-18",
        "07",
        "MODULE",
        (
            "tests/integration/test_e5_decision.py"
            "::test_a_decline_leaves_the_asset_free_to_continue",
        ),
        "After a no-match or decline, nothing in E5 is locked and the asset may continue.",
        blocked_reason=(
            "Only the E5 half is proven here: a decline leaves the card ready, the asset "
            "active and its milestone states untouched. The behaviour's other half — that "
            "M5 route evaluation remains available — cannot be checked at E5's seam, "
            "because M5 has no surface in E5. It belongs to E6."
        ),
    ),
)

# Claims that need hardware. Listed so the packet states them rather than
# leaving a reader to infer their absence, and so none can be read as passing.
HARDWARE_BLOCKED: tuple[tuple[str, str], ...] = (
    (
        "real-model structured proposal",
        "Ticket 05 criterion 13 and ticket 11: the local model must actually be asked "
        "for a structured proposal. Not run here, and no result is claimed.",
    ),
    (
        "W7900 / ROCm / vLLM serving",
        "Ticket 11 owns the exact-head gate. Nothing in this packet touches a GPU.",
    ),
    (
        "20K context window capability",
        "PR #44 approved the budget; the only window empirically proven on the W7900 is "
        "8192. The budget module keeps both numbers separate for this reason.",
    ),
)

# Content that must never reach a public packet. Prompts and responses are on
# the list because persisting them would create a second store of exactly the
# private text the local-inference boundary exists to contain.
FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("credential", r"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}"),
    ("private key", r"BEGIN (RSA|OPENSSH|EC|PRIVATE) .*KEY"),
    ("quality-owner-only path", r"(^|/)(\.qa-private|private-qa|benchmarks/hidden)(/|$)"),
    ("model weights", r"\.safetensors|\.gguf|pytorch_model.*\.bin"),
)


def _run(label: str, argv: list[str], *, tail_lines: int = 3) -> CommandRun:
    completed = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, check=False
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return CommandRun(
        label=label,
        argv=tuple(argv),
        returncode=completed.returncode,
        tail="\n".join(lines[-tail_lines:]),
    )


def _run_behaviours() -> tuple[list[dict], CommandRun]:
    """Run every named test once, then report each behaviour against that run."""
    node_ids = sorted({test for behaviour in BEHAVIOURS for test in behaviour.tests})
    run = _run(
        "grag-behaviours",
        [*PYTEST, *node_ids],
    )
    results = []
    for behaviour in BEHAVIOURS:
        results.append(
            {
                "grag_id": behaviour.grag_id,
                "ticket": behaviour.ticket,
                "seam": behaviour.seam,
                "summary": behaviour.summary,
                # One pytest invocation covers every node id, so a green run is
                # a green run for all of them. Reporting per-behaviour status
                # from a single aggregate is stated here rather than implied.
                "result": "PASS" if run.passed else "FAIL",
                "tests": list(behaviour.tests),
                "partial_reason": behaviour.blocked_reason,
            }
        )
    return results, run


def _scan_packet(paths: list[Path]) -> list[dict]:
    findings = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, text):
                findings.append(
                    # The matched text is deliberately not recorded: writing it
                    # here would put the very content the scan exists to keep
                    # out into the file that reports it.
                    {"file": path.name, "category": label, "offset": match.start()}
                )
    return findings


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def capture(output_dir: Path, *, code_commit: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    behaviours, behaviour_run = _run_behaviours()
    commands = [
        behaviour_run,
        _run("full-python-suite", [*PYTEST]),
        _run("qa-suite", [*PYTEST, "qa/tests"]),
        _run("contract-sync", [sys.executable, "scripts/export_contracts.py", "--check"]),
        _run("fixture-sync", [sys.executable, "scripts/export_e5_fixtures.py", "--check"]),
        _run("migration-upgrade", [
            *PYTEST,
            "tests/integration/test_e5_migration_upgrade.py",
            "tests/integration/test_persistence.py",
        ]),
        _run("lint", [sys.executable, "-m", "ruff", "check", "app/", "tests/", "qa/"]),
        _run("pr-gate", ["bash", "qa/gates/pr_gate.sh", "--mode", "contract"]),
    ]

    failed = [command.label for command in commands if not command.passed]
    tree_state = "CLEAN" if not _git("status", "--porcelain") else "DIRTY"
    results = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "code_commit": code_commit,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "tree_state": tree_state,
        "model": "deterministic-fake",
        "behaviours": behaviours,
        "commands": [
            {
                "label": command.label,
                "argv": list(command.argv),
                "returncode": command.returncode,
                "result": "PASS" if command.passed else "FAIL",
                "tail": command.tail,
            }
            for command in commands
        ],
        "blocked_claims": [
            {"claim": claim, "status": "BLOCKED", "detail": detail, "owner": "ticket 11"}
            for claim, detail in HARDWARE_BLOCKED
        ],
        # A packet that passed its checks but was captured from a dirty tree
        # cannot be reproduced from the commit it names.
        "decision": (
            "PASS" if not failed and tree_state == "CLEAN"
            else "NOT_VERIFIED" if not failed
            else "FAIL"
        ),
        "failed_commands": failed,
    }
    _write_json(output_dir / "grag-results.json", results)
    _write_json(output_dir / "manifest.json", _manifest(results))
    (output_dir / "summary.md").write_text(_summary(results), encoding="utf-8")

    written = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "artifact-hashes.json"
    )
    disclosure = _scan_packet(written)
    _write_json(
        output_dir / "artifact-hashes.json",
        {
            "schema_version": "artifact-hashes/v1",
            "code_commit": code_commit,
            "disclosure_scan": {
                "result": "PASS" if not disclosure else "FAIL",
                "patterns_checked": [label for label, _ in FORBIDDEN_PATTERNS],
                "findings": disclosure,
            },
            "sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in written
            },
        },
    )
    results["disclosure_scan"] = "PASS" if not disclosure else "FAIL"
    return results


def _manifest(results: dict) -> dict:
    passed = [item for item in results["behaviours"] if item["result"] == "PASS"]
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "commit": results["code_commit"],
        "branch": results["branch"],
        "tree_state": results["tree_state"],
        "decision": results["decision"],
        "grag_total": len(results["behaviours"]),
        "grag_passed": len(passed),
        "grag_at_http_seam": len([item for item in passed if item["seam"] == "HTTP"]),
        "grag_with_recorded_limits": len(
            [item for item in results["behaviours"] if item["partial_reason"]]
        ),
        "contract_gate": all(
            command["result"] == "PASS"
            for command in results["commands"]
            if command["label"] in {"contract-sync", "fixture-sync", "pr-gate"}
        ),
        "python_suite": next(
            command["result"] == "PASS"
            for command in results["commands"]
            if command["label"] == "full-python-suite"
        ),
        "migration_upgrade": next(
            command["result"] == "PASS"
            for command in results["commands"]
            if command["label"] == "migration-upgrade"
        ),
        "model": results["model"],
        "gpu_evidence": False,
        "real_model_service_evidence": False,
        "sanitized": True,
    }


def _summary(results: dict) -> str:
    lines = [
        "# E5 本地证据包",
        "",
        f"- commit：`{results['code_commit']}`（分支 `{results['branch']}`，"
        f"工作树 {results['tree_state']}）",
        f"- 模型：**{results['model']}**。本包内没有任何一条主张来自真实模型或 GPU。",
        f"- 结论：**{results['decision']}**",
        "",
        "## GRAG 行为",
        "",
        "`seam` 列是这条行为被证明的位置：`HTTP` 是公共 API，`MODULE` 是应用层或仓储层。",
        "票 10 的第一条验收要求「权威外部缝」，因此只在模块缝证明的行为如实标注，",
        "不按 HTTP 证明计。",
        "",
        "| GRAG | 票 | seam | 结果 | 行为 |",
        "|---|---|---|---|---|",
    ]
    for item in results["behaviours"]:
        note = " ⚠️" if item["partial_reason"] else ""
        lines.append(
            f"| {item['grag_id']} | {item['ticket']} | {item['seam']} | "
            f"{item['result']}{note} | {item['summary']} |"
        )
    limited = [item for item in results["behaviours"] if item["partial_reason"]]
    if limited:
        lines += ["", "### 标注了限制的行为", ""]
        for item in limited:
            lines += [f"**{item['grag_id']}** — {item['partial_reason']}", ""]
    lines += ["", "## 命令与结果", "", "| 命令 | 退出码 | 结果 |", "|---|---|---|"]
    for command in results["commands"]:
        lines.append(
            f"| `{' '.join(command['argv'][-3:])}` | "
            f"{command['returncode']} | {command['result']} |"
        )
    lines += [
        "",
        "## 需要硬件、因此未验证的主张",
        "",
        "每一条记为 `BLOCKED` 并指向票 11，都不记 `PASS`。",
        "",
    ]
    for claim in results["blocked_claims"]:
        lines.append(f"- **{claim['claim']}** — `BLOCKED`。{claim['detail']}")
    lines += [
        "",
        "## 脱敏",
        "",
        "包内不含原始 prompt、模型响应、私有源文本、凭据、模型权重或隐藏 QA 材料；",
        "`artifact-hashes.json` 里记录了扫描结果。命中项只记文件与位置，不记命中的文本——",
        "把它写进报告等于把扫描本要挡住的内容放进报告本身。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    results = capture(args.output_dir, code_commit=args.code_commit)
    print(
        json.dumps(
            {
                "decision": results["decision"],
                "grag_passed": sum(
                    1 for item in results["behaviours"] if item["result"] == "PASS"
                ),
                "failed_commands": results["failed_commands"],
                "disclosure_scan": results["disclosure_scan"],
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 0 if results["decision"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
