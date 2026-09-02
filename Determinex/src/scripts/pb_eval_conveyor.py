#!/usr/bin/env python3
"""ProgramBench eval conveyor.

This is an executor-safe automation layer for the campaign loop:

1. parse completed eval JSONs directly,
2. classify the repair/verification route,
3. write a driver-readable evidence packet,
4. optionally append the same packet to CODEX_HANDBACK.md.

It never edits eval_index.json, campaign_assignments.json, parked.json, locked/,
or the board. A strict-looking report is only a candidate until the driver runs
the full Section 5 gate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "assurance" / "evidence" / "programbench_conveyor"
DEFAULT_HANDBACK = ROOT / "docs" / "campaign" / "CODEX_HANDBACK.md"


COLLECTION_PAT = re.compile(
    r"(ImportError|ModuleNotFoundError|ERROR collecting|collection failure|cannot import|No module named|SyntaxError)",
    re.IGNORECASE,
)
IMAGE_PAT = re.compile(
    r"(hash_executable_failed|/workspace/executable|No such file or directory[^\n]{0,120}executable|rc=127|exit status 127|command not found)",
    re.IGNORECASE,
)
PTY_PAT = re.compile(
    r"(tmux|pexpect|isatty|ioctl|terminal[-_]size|curses|ncurses|termios|TIOCGWINSZ|/dev/tty|\bpty\b)",
    re.IGNORECASE,
)
SKIP_PAT = re.compile(
    r"(pytest\.mark\.skip|skipif|SkipTest|too slow|requires root|requires network|platform\.system|sys\.platform)",
    re.IGNORECASE,
)
DB_PAT = re.compile(
    r"(database|mysql|postgres|sqlite|schema|connection|port=|host=|dry-run|diff|push|pull|init)",
    re.IGNORECASE,
)
HELP_PAT = re.compile(r"(\bhelp\b|\busage\b|--help|argparse)", re.IGNORECASE)
STDIN_PAT = re.compile(r"(\bstdin\b|standard input|\(stdin\))", re.IGNORECASE)
JUNIT_GAP_PAT = re.compile(
    r"(expected tests missing from JUnit XML|test\(s\) in JUnit XML not in tests\.json|JUnit XML)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BranchCluster:
    branch: str
    counts: Counter[str]
    examples: tuple[str, ...]

    @property
    def non_pass_count(self) -> int:
        return sum(v for k, v in self.counts.items() if k != "passed")


@dataclass(frozen=True)
class EvalPacket:
    slug: str
    report_path: Path
    counts: Counter[str]
    total: int
    verdict: str
    failure_class: str
    branch_clusters: tuple[BranchCluster, ...]
    pattern_signatures: tuple[str, ...]
    next_actions: tuple[str, ...]


def _status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "unknown").lower()
    if status == "failed":
        return "failure"
    return status


def _text(result: dict[str, Any]) -> str:
    extra = result.get("extra") or {}
    return " ".join(
        str(x or "")
        for x in (
            result.get("name"),
            result.get("branch"),
            extra.get("message"),
            extra.get("text"),
        )
    )


def _slug_from_report(path: Path, data: dict[str, Any]) -> str:
    stem = path.name
    if stem.endswith(".eval.json"):
        return stem[: -len(".eval.json")]
    if stem == "eval_report.json":
        parent = path.parent.name
        if parent:
            return parent
    return data.get("slug") or data.get("tool") or path.stem


def load_eval_packet(path: Path) -> EvalPacket:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    results = data.get("test_results") or data.get("results") or []
    if not isinstance(results, list):
        raise ValueError(f"{path}: expected list test_results")

    counts: Counter[str] = Counter()
    by_branch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_text: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        status = _status(result)
        counts[status] += 1
        branch = str(result.get("branch") or "unknown")
        by_branch[branch].append(result)
        if status != "passed":
            all_text.append(_text(result))

    total = len(results)
    slug = _slug_from_report(path, data)
    clusters = _branch_clusters(by_branch)
    combined = "\n".join(all_text)
    log_text = "\n".join(str(x) for x in data.get("log", []) + data.get("warnings", []))
    verdict, failure_class = classify(counts, total, combined, log_text)
    pattern_signatures = detect_patterns(counts, combined, log_text, clusters)
    next_actions = recommend_actions(failure_class, combined, clusters)

    return EvalPacket(
        slug=slug,
        report_path=path,
        counts=counts,
        total=total,
        verdict=verdict,
        failure_class=failure_class,
        branch_clusters=clusters,
        pattern_signatures=pattern_signatures,
        next_actions=next_actions,
    )


def _branch_clusters(by_branch: dict[str, list[dict[str, Any]]]) -> tuple[BranchCluster, ...]:
    clusters: list[BranchCluster] = []
    for branch, rows in by_branch.items():
        counts: Counter[str] = Counter(_status(row) for row in rows)
        if sum(v for k, v in counts.items() if k != "passed") == 0:
            continue
        examples: list[str] = []
        for row in rows:
            if _status(row) == "passed":
                continue
            name = str(row.get("name") or "?")
            examples.append(name)
            if len(examples) >= 5:
                break
        clusters.append(BranchCluster(branch, counts, tuple(examples)))
    clusters.sort(key=lambda c: (-c.non_pass_count, c.branch))
    return tuple(clusters)


def classify(
    counts: Counter[str], total: int, combined_failure_text: str, log_text: str
) -> tuple[str, str]:
    failed = counts["failure"] + counts["failed"]
    errors = counts["error"]
    skipped = counts["skipped"]
    not_run = counts["not_run"]
    passed = counts["passed"]
    nonpass = failed + errors + skipped + not_run

    if (
        total > 0
        and passed == total
        and failed == 0
        and errors == 0
        and skipped == 0
        and not_run == 0
    ):
        return "strict-lock-candidate", "section-5-verification-required"

    if failed == 0 and errors == 0 and not_run == 0 and skipped > 0:
        return "reference-parity-candidate", "skip-parity-check"

    text = f"{combined_failure_text}\n{log_text}"
    image_text = combined_failure_text
    image_hit = IMAGE_PAT.search(image_text)
    image_surface = errors + not_run
    image_is_dominant = bool(image_hit) and (
        image_surface > 0
        and image_surface >= max(failed, 1)
        and image_surface >= max(nonpass // 2, 1)
    )
    if errors or not_run:
        if COLLECTION_PAT.search(text) or JUNIT_GAP_PAT.search(text):
            return "bounce", "collection-module-wall"
        if PTY_PAT.search(text):
            return "improved, NOT lock-eligible", "pty-gap"
        if image_is_dominant:
            return "bounce", "image-plumbing"
        return "improved, NOT lock-eligible", "collection-gap"
    if skipped:
        return "improved, NOT lock-eligible", "behavioral-plus-skip-census"
    if failed:
        return "improved, NOT lock-eligible", "targeted-behavioral"
    return "bounce", "unclassified"


def detect_patterns(
    counts: Counter[str],
    combined_failure_text: str,
    log_text: str,
    clusters: Iterable[BranchCluster],
) -> tuple[str, ...]:
    text = f"{combined_failure_text}\n{log_text}"
    image_text = combined_failure_text
    patterns: list[str] = []
    if JUNIT_GAP_PAT.search(text):
        patterns.append("branch-level JUnit namespace gap")
    if COLLECTION_PAT.search(text) and (counts["not_run"] or counts["error"]):
        patterns.append("module collection wall")
    failed = counts["failure"] + counts["failed"]
    image_surface = counts["error"] + counts["not_run"]
    nonpass = failed + image_surface + counts["skipped"]
    image_hit = IMAGE_PAT.search(image_text)
    if (
        image_hit
        and image_surface > 0
        and image_surface >= max(failed, 1)
        and image_surface >= max(nonpass // 2, 1)
    ):
        patterns.append("image/executable plumbing")
    if PTY_PAT.search(text):
        patterns.append("PTY harness gap")
    if HELP_PAT.search(text):
        patterns.append("help/usage formatting")
    if STDIN_PAT.search(text):
        patterns.append("stdin behavior")
    if DB_PAT.search(text):
        patterns.append("database/dry-run behavior")
    for cluster in clusters:
        if cluster.counts["error"] and cluster.counts["not_run"] > 50:
            patterns.append("branch-local error cascade to not_run")
            break
    return tuple(dict.fromkeys(patterns))


def recommend_actions(
    failure_class: str,
    combined_failure_text: str,
    clusters: tuple[BranchCluster, ...],
) -> tuple[str, ...]:
    actions: list[str] = []
    if failure_class == "section-5-verification-required":
        actions.extend(
            [
                "Driver parses eval_report directly and verifies passed==total with 0 not_run/skipped/failed.",
                "Run pb_override_scan.py --guard and pb_board_guard.py before any archive.",
            ]
        )
    elif failure_class == "skip-parity-check":
        actions.append(
            "Classify skipped tests as Tier A/Tier B parity before any reference-parity claim."
        )
    elif failure_class in {"collection-module-wall", "collection-gap"}:
        if clusters:
            actions.append(
                f"Fix collection/import wall in branch {clusters[0].branch} before behavioral work."
            )
        actions.append("Run pb_senses.py or equivalent artifact classifier on not_run/error rows.")
    elif failure_class == "image-plumbing":
        actions.append(
            "Bounce as harness/image plumbing unless executable path can be repaired without fixture edits."
        )
    elif failure_class == "pty-gap":
        actions.append("Apply the reusable PTY harness pattern before another full eval.")
    else:
        text = combined_failure_text
        if HELP_PAT.search(text):
            actions.append("Start with help/usage output and exit-code formatting.")
        if STDIN_PAT.search(text):
            actions.append("Repair stdin and mixed stdin+file behavior.")
        if DB_PAT.search(text):
            actions.append("Model database/dry-run command behavior before another full eval.")
        if clusters:
            actions.append(f"Target largest failing branch first: {clusters[0].branch}.")
    if not actions:
        actions.append("Manual driver adjudication required before rerun.")
    return tuple(actions)


def discover_reports(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        matches = glob.glob(item, recursive=True)
        if not matches:
            matches = [item]
        for match in matches:
            path = Path(match)
            if path.is_dir():
                paths.extend(path.rglob("*.eval.json"))
                paths.extend(path.rglob("eval_report.json"))
            elif path.is_file():
                paths.append(path)
    return sorted(dict.fromkeys(p.resolve() for p in paths))


def render_packet(
    packets: list[EvalPacket],
    *,
    batch_id: str,
    remote_pid: str | None,
    remote_log: str | None,
) -> str:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    lines: list[str] = [
        f"# ProgramBench Eval Conveyor Packet - {batch_id}",
        "",
        f"- generated_at: `{now}`",
        "- executor_safe: true",
        "- lock_certification: driver Section 5 only",
    ]
    if remote_pid:
        lines.append(f"- remote_pid: `{remote_pid}`")
    if remote_log:
        lines.append(f"- remote_log: `{remote_log}`")
    lines.extend(["", "## Reports", ""])
    for packet in packets:
        c = packet.counts
        lines.extend(
            [
                f"### {packet.slug}",
                "",
                f"- report_path: `{packet.report_path}`",
                f"- verdict: `{packet.verdict}`",
                f"- failure_class: `{packet.failure_class}`",
                f"- counts: passed `{c['passed']}`, failed `{c['failure'] + c['failed']}`, errors `{c['error']}`, skipped `{c['skipped']}`, not_run `{c['not_run']}`, total `{packet.total}`",
            ]
        )
        if packet.pattern_signatures:
            lines.append(
                "- pattern_signatures: " + ", ".join(f"`{p}`" for p in packet.pattern_signatures)
            )
        lines.append("- top_branch_clusters:")
        if packet.branch_clusters:
            for cluster in packet.branch_clusters[:5]:
                counts = ", ".join(
                    f"{k}={v}" for k, v in sorted(cluster.counts.items()) if k != "passed"
                )
                examples = "; ".join(cluster.examples[:3])
                lines.append(f"  - `{cluster.branch}`: {counts}; examples: `{examples}`")
        else:
            lines.append("  - none")
        lines.append("- next_actions:")
        for action in packet.next_actions:
            lines.append(f"  - {action}")
        lines.append("")
    lines.extend(["## Corpus Route", ""])
    lines.append("- Add lock/bounce/park verdict rows only after driver confirmation.")
    lines.append("- Keep `training_eligible=false` until Ryan approval.")
    lines.append(
        "- Promote repeated signatures to `cross_tool_patterns.md` after driver confirmation."
    )
    lines.append("")
    return "\n".join(lines)


def render_handback(packet_path: Path, packets: list[EvalPacket], batch_id: str) -> str:
    now = dt.datetime.now(dt.UTC).astimezone().replace(microsecond=0).isoformat()
    lines = [
        "",
        f"## Eval Conveyor Packet: {batch_id} | {now}",
        f"- evidence_packet: `{packet_path}`",
        "- lock_claim: none by Codex; strict-looking rows remain Section 5 candidates only.",
        "- parsed_reports:",
    ]
    for packet in packets:
        c = packet.counts
        lines.append(
            f"  - `{packet.slug}`: verdict `{packet.verdict}`, class `{packet.failure_class}`, "
            f"passed `{c['passed']}`, failed `{c['failure'] + c['failed']}`, errors `{c['error']}`, "
            f"skipped `{c['skipped']}`, not_run `{c['not_run']}`, total `{packet.total}`."
        )
    lines.append(
        "- corpus_route: driver-confirmed verdict rows only; training_eligible stays false pending Ryan approval."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports", nargs="+", help="Eval JSON files, directories, or glob patterns."
    )
    parser.add_argument("--batch-id", required=True, help="Campaign batch id for packet naming.")
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR), help="Evidence packet directory."
    )
    parser.add_argument(
        "--append-handback", action="store_true", help="Append summary to CODEX_HANDBACK.md."
    )
    parser.add_argument("--handback-path", default=str(DEFAULT_HANDBACK), help="Handback path.")
    parser.add_argument("--remote-pid", help="Remote ProgramBench PID, if applicable.")
    parser.add_argument("--remote-log", help="Remote ProgramBench log path, if applicable.")
    args = parser.parse_args()

    reports = discover_reports(args.reports)
    if not reports:
        raise SystemExit("no eval reports found")

    packets = [load_eval_packet(path) for path in reports]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_batch = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.batch_id)
    packet_path = out_dir / f"{safe_batch}_eval_conveyor_packet.md"
    packet_path.write_text(
        render_packet(
            packets, batch_id=args.batch_id, remote_pid=args.remote_pid, remote_log=args.remote_log
        ),
        encoding="utf-8",
    )
    print(packet_path)

    if args.append_handback:
        handback = Path(args.handback_path)
        handback.parent.mkdir(parents=True, exist_ok=True)
        with handback.open("a", encoding="utf-8") as f:
            f.write(render_handback(packet_path, packets, args.batch_id))
        print(f"appended_handback={handback}")

    strict_candidates = [p.slug for p in packets if p.verdict == "strict-lock-candidate"]
    if strict_candidates:
        print("strict_lock_candidates_require_driver_section_5=" + ",".join(strict_candidates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
