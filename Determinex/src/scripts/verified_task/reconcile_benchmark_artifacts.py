#!/usr/bin/env python3
"""Find benchmark artifacts that have not resolved into corpus status.

The reconciler enforces the bench law:

  every benchmark output -> signed training row | signed eval evidence |
  signed reject | signed infrastructure failure

It is deliberately conservative. It flags missing manifests, eval JSONs without
gate/corpus status nearby, orphan logs, and shard manifests without terminal
state.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TERMINAL_STATES = {"cleaned", "failed", "ignored", "pulled", "gated", "accepted", "rejected"}
ALLOWED_TRACE_STATUSES = {
    "active_training_eligible",
    "active_eval_evidence",
    "rejected",
    "quarantined",
    "infra_failure",
}


@dataclass
class ReconcileIssue:
    kind: str
    path: str
    detail: str


@dataclass
class ReconcileReport:
    roots: list[str]
    eval_json_count: int = 0
    manifest_count: int = 0
    log_count: int = 0
    corpus_trace_count: int = 0
    issue_count: int = 0
    issues: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_roots(
    roots: Iterable[Path], *, active_manifest: Path | None = None
) -> ReconcileReport:
    root_list = [Path(r) for r in roots]
    report = ReconcileReport(roots=[str(r) for r in root_list])
    corpus_trace_roots = _corpus_trace_roots(root_list)

    for root in root_list:
        if not root.exists():
            continue
        for eval_json in root.rglob("*.eval.json"):
            report.eval_json_count += 1
            if not _has_nearby_status(eval_json):
                _issue(
                    report,
                    "eval_without_status",
                    eval_json,
                    "missing gate_result.json or corpus trace near eval",
                )
        for manifest in root.rglob("manifest.json"):
            report.manifest_count += 1
            _check_manifest(report, manifest)
        for log in list(root.rglob("*.log")) + list(root.rglob("*.err.log")):
            report.log_count += 1
            if not _has_manifest_ancestor(log):
                _issue(report, "orphan_log", log, "log has no manifest ancestor")

    for trace in corpus_trace_roots:
        report.corpus_trace_count += 1
        if trace.get("status") not in ALLOWED_TRACE_STATUSES:
            _issue(
                report, "trace_bad_status", Path(trace.get("path", "")), str(trace.get("status"))
            )

    if active_manifest and active_manifest.is_file():
        _check_active_manifest(report, active_manifest)

    report.issue_count = len(report.issues)
    return report


def _check_manifest(report: ReconcileReport, manifest: Path) -> None:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        _issue(report, "manifest_parse_error", manifest, str(exc))
        return
    if isinstance(data, dict) and data.get("items") is not None:
        # Shard manifests should eventually have pulled/gated state in active manifest.
        return
    if (
        isinstance(data, dict)
        and data.get("corpus_trace")
        and not Path(str(data["corpus_trace"])).exists()
    ):
        _issue(report, "manifest_missing_corpus_trace", manifest, str(data["corpus_trace"]))


def _check_active_manifest(report: ReconcileReport, active_manifest: Path) -> None:
    data = json.loads(active_manifest.read_text(encoding="utf-8", errors="replace"))
    shards = data.get("shards") if isinstance(data, dict) else {}
    if not isinstance(shards, dict):
        _issue(report, "active_manifest_bad_shape", active_manifest, "missing shards object")
        return
    for name, row in shards.items():
        state = str((row or {}).get("state") or "")
        if state and state not in TERMINAL_STATES and state != "remote_running":
            _issue(report, "shard_unknown_state", active_manifest, f"{name}:{state}")
        if state == "remote_running":
            _issue(report, "shard_still_running", active_manifest, str(name))


def _corpus_trace_roots(roots: list[Path]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for root in roots:
        for path in root.rglob("*.jsonl") if root.exists() else []:
            try:
                for line_no, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        continue
                    status = row.get("record_status") or row.get("trace_status")
                    if status:
                        traces.append({"path": f"{path}:{line_no}", "status": status})
            except (OSError, json.JSONDecodeError):
                continue
    return traces


def _has_nearby_status(eval_json: Path) -> bool:
    candidates = [
        eval_json.parent / "gate_result.json",
        eval_json.parent.parent / "gate_result.json",
        eval_json.parent / "corpus_trace.json",
        eval_json.parent.parent / "corpus_trace.json",
    ]
    return any(path.exists() for path in candidates)


def _has_manifest_ancestor(path: Path) -> bool:
    for parent in [path.parent, *path.parents]:
        if (parent / "manifest.json").is_file():
            return True
    return False


def _issue(report: ReconcileReport, kind: str, path: Path, detail: str) -> None:
    report.issues.append(asdict(ReconcileIssue(kind=kind, path=str(path), detail=detail)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--active-manifest", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    report = reconcile_roots(args.roots, active_manifest=args.active_manifest)
    text = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(text)
    return 1 if report.issue_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
