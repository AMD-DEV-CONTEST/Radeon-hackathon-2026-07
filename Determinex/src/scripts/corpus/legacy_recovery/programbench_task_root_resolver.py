#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.programbench_source_index import (
    ProgramBenchSourceEntry,
    ProgramBenchSourceIndex,
)
from corpus.legacy_recovery.programbench_tool_alias_index import (
    aliases_for_tool,
    normalized_slug,
    normalized_tool_name,
)


class ResolutionStatus(str, Enum):
    TASK_ROOT_RESOLVED = "TASK_ROOT_RESOLVED"
    SOURCE_ROOT_RESOLVED = "SOURCE_ROOT_RESOLVED"
    TASK_AND_SOURCE_RESOLVED = "TASK_AND_SOURCE_RESOLVED"
    AMBIGUOUS_TOOL_MATCH = "AMBIGUOUS_TOOL_MATCH"
    NO_MATCH = "NO_MATCH"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    ALIAS_ONLY_MATCH = "ALIAS_ONLY_MATCH"
    BINARY_ONLY_MATCH = "BINARY_ONLY_MATCH"
    METADATA_ONLY_MATCH = "METADATA_ONLY_MATCH"


@dataclass(slots=True)
class ResolutionConfig:
    roots: list[Path]
    output_path: Path = Path("assurance/evidence/programbench_task_root_resolution_batch_001.json")
    allowed_roots: list[Path] | None = None


@dataclass(slots=True)
class ResolutionResult:
    tool: str
    legacy_row_hash: str
    resolution_status: str
    task_root: str = ""
    source_root: str = ""
    confidence: float = 0.0
    method: str = ""
    matched_slug: str = ""
    language_guess: str = "unknown"
    failure_class: str = "unknown"
    duplicate_cluster_id: str = ""
    candidate_root: str = ""
    reason: str = ""


class ProgramBenchTaskRootResolver:
    def __init__(self, config: ResolutionConfig) -> None:
        self.config = config
        self.allowed_roots = config.allowed_roots or config.roots
        self.index = ProgramBenchSourceIndex(config.roots)

    def resolve_batch(self, batch_artifact: Path) -> dict[str, Any]:
        batch = json.loads(batch_artifact.read_text(encoding="utf-8"))
        candidates = list(batch.get("selected") or [])
        results = [self.resolve_candidate(candidate) for candidate in candidates]
        counts: dict[str, int] = {status.value: 0 for status in ResolutionStatus}
        for result in results:
            counts[result.resolution_status] += 1
        resolved_statuses = {
            ResolutionStatus.TASK_ROOT_RESOLVED.value,
            ResolutionStatus.SOURCE_ROOT_RESOLVED.value,
            ResolutionStatus.TASK_AND_SOURCE_RESOLVED.value,
        }
        report = {
            "schema_version": "determinex-programbench-task-root-resolution-v1",
            "batch_id": "legacy_replay_promotion_batch_001",
            "source_batch": str(batch_artifact),
            "candidates": len(candidates),
            "resolved": sum(
                1 for result in results if result.resolution_status in resolved_statuses
            ),
            "ambiguous": sum(
                1
                for result in results
                if result.resolution_status
                in {
                    ResolutionStatus.AMBIGUOUS_TOOL_MATCH.value,
                    ResolutionStatus.MULTIPLE_MATCHES.value,
                }
            ),
            "missing": sum(
                1
                for result in results
                if result.resolution_status == ResolutionStatus.NO_MATCH.value
            ),
            "status_counts": {k: v for k, v in counts.items() if v},
            "results": [asdict(result) for result in results],
            "policy": "Resolution maps legacy candidate identity to existing ProgramBench roots only; it does not run verifier or promote rows.",
        }
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    def resolve_candidate(self, candidate: dict[str, Any]) -> ResolutionResult:
        base = _base_result(candidate)
        if not base.tool:
            base.resolution_status = ResolutionStatus.NO_MATCH.value
            base.reason = "missing_tool"
            return base

        exact = self.index.find_exact(normalized_slug(base.tool))
        exact = _filter_safe(exact, self.allowed_roots)
        if len(exact) == 1:
            return _resolved(
                base, exact[0], ResolutionStatus.TASK_AND_SOURCE_RESOLVED, 1.0, "exact_tool_name"
            )
        if len(exact) > 1:
            return _ambiguous(
                base, exact, ResolutionStatus.MULTIPLE_MATCHES, "multiple_exact_matches"
            )

        alias_values = [
            alias
            for alias in aliases_for_tool(base.tool)
            if alias != normalized_tool_name(base.tool)
        ]
        alias_matches: list[ProgramBenchSourceEntry] = []
        for alias in alias_values:
            alias_matches.extend(self.index.find_by_key(alias))
        alias_matches = _dedupe_entries(_filter_safe(alias_matches, self.allowed_roots))
        if len(alias_matches) == 1:
            return _resolved(
                base, alias_matches[0], ResolutionStatus.ALIAS_ONLY_MATCH, 0.85, "alias_table"
            )
        if len(alias_matches) > 1:
            return _ambiguous(
                base, alias_matches, ResolutionStatus.AMBIGUOUS_TOOL_MATCH, "multiple_alias_matches"
            )

        binary = self.index.find_by_binary(normalized_tool_name(base.tool))
        binary = _dedupe_entries(_filter_safe(binary, self.allowed_roots))
        if len(binary) == 1:
            return _resolved(
                base, binary[0], ResolutionStatus.BINARY_ONLY_MATCH, 0.7, "binary_name_scan"
            )
        if len(binary) > 1:
            return _ambiguous(
                base, binary, ResolutionStatus.AMBIGUOUS_TOOL_MATCH, "multiple_binary_matches"
            )

        base.resolution_status = ResolutionStatus.NO_MATCH.value
        base.reason = "no_index_match"
        return base


def default_config(output_path: Path) -> ResolutionConfig:
    roots = [
        Path("T:/determinex-programbench"),
        Path("T:/Dev/ProgramBench"),
        Path("corpus/programbench/per_tool_overrides"),
        Path("corpus/programbench/in_progress"),
        Path("corpus/programbench/locked"),
    ]
    return ResolutionConfig(roots=roots, allowed_roots=roots, output_path=output_path)


def _base_result(candidate: dict[str, Any]) -> ResolutionResult:
    classes = candidate.get("failure_classes") or ["unknown"]
    return ResolutionResult(
        tool=str(candidate.get("tool") or ""),
        legacy_row_hash=str(candidate.get("legacy_row_hash") or ""),
        resolution_status=ResolutionStatus.NO_MATCH.value,
        language_guess=str(candidate.get("language_guess") or "unknown"),
        failure_class=str(classes[0]),
        duplicate_cluster_id=str(candidate.get("duplicate_cluster_id") or ""),
    )


def _resolved(
    base: ResolutionResult,
    entry: ProgramBenchSourceEntry,
    status: ResolutionStatus,
    confidence: float,
    method: str,
) -> ResolutionResult:
    base.resolution_status = status.value
    base.task_root = entry.root
    base.source_root = entry.source_root
    base.candidate_root = entry.root
    base.matched_slug = entry.slug
    base.confidence = confidence
    base.method = method
    base.reason = "resolved"
    return base


def _ambiguous(
    base: ResolutionResult,
    entries: list[ProgramBenchSourceEntry],
    status: ResolutionStatus,
    reason: str,
) -> ResolutionResult:
    base.resolution_status = status.value
    base.reason = reason
    base.confidence = 0.0
    base.method = "ambiguous"
    base.matched_slug = ",".join(entry.slug for entry in entries[:5])
    return base


def _filter_safe(
    entries: list[ProgramBenchSourceEntry], roots: list[Path]
) -> list[ProgramBenchSourceEntry]:
    out: list[ProgramBenchSourceEntry] = []
    for entry in entries:
        root = Path(entry.root)
        source = Path(entry.source_root)
        if not root.exists() or not source.exists():
            continue
        if not _inside_any(root, roots) or not _inside_any(source, roots):
            continue
        out.append(entry)
    return out


def _inside_any(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        if not root.exists():
            continue
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _dedupe_entries(entries: list[ProgramBenchSourceEntry]) -> list[ProgramBenchSourceEntry]:
    seen: set[str] = set()
    out: list[ProgramBenchSourceEntry] = []
    for entry in entries:
        key = str(Path(entry.root).resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve legacy ProgramBench replay candidates to task/source roots."
    )
    parser.add_argument("batch_artifact", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/programbench_task_root_resolution_batch_001.json"),
    )
    parser.add_argument("--root", action="append", type=Path, default=None)
    args = parser.parse_args()

    config = default_config(args.output)
    if args.root is not None:
        config.roots = args.root
        config.allowed_roots = args.root
    report = ProgramBenchTaskRootResolver(config).resolve_batch(args.batch_artifact)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
