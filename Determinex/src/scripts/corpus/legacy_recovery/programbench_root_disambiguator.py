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
from corpus.legacy_recovery.programbench_tool_alias_index import normalized_slug


class DisambiguationStatus(str, Enum):
    CANONICAL_ROOT_SELECTED = "CANONICAL_ROOT_SELECTED"
    OVERRIDE_ROOT_SELECTED = "OVERRIDE_ROOT_SELECTED"
    LOCKED_ROOT_SELECTED = "LOCKED_ROOT_SELECTED"
    ACTIVE_RUN_ROOT_SELECTED = "ACTIVE_RUN_ROOT_SELECTED"
    T_DRIVE_RUN_ROOT_SELECTED = "T_DRIVE_RUN_ROOT_SELECTED"
    AMBIGUOUS_NEEDS_OVERRIDE = "AMBIGUOUS_NEEDS_OVERRIDE"
    NO_RUNNABLE_ROOT = "NO_RUNNABLE_ROOT"
    UNSAFE_ROOT_REJECTED = "UNSAFE_ROOT_REJECTED"


SELECTED_STATUSES = {
    DisambiguationStatus.CANONICAL_ROOT_SELECTED.value,
    DisambiguationStatus.OVERRIDE_ROOT_SELECTED.value,
    DisambiguationStatus.LOCKED_ROOT_SELECTED.value,
    DisambiguationStatus.ACTIVE_RUN_ROOT_SELECTED.value,
    DisambiguationStatus.T_DRIVE_RUN_ROOT_SELECTED.value,
}


@dataclass(slots=True)
class RootDisambiguationConfig:
    roots: list[Path]
    allowed_roots: list[Path]
    overrides_path: Path = Path("assurance/config/programbench_root_overrides.json")
    output_path: Path = Path("assurance/evidence/programbench_root_disambiguation_batch_001.json")


@dataclass(slots=True)
class RootDisambiguationResult:
    tool: str
    legacy_row_hash: str
    status: str
    candidate_roots: int
    selected_root: str = ""
    selected_source_root: str = ""
    confidence: float = 0.0
    method: str = ""
    evidence: list[str] | None = None
    reason: str = ""


class ProgramBenchRootDisambiguator:
    def __init__(self, config: RootDisambiguationConfig) -> None:
        self.config = config
        self.index = ProgramBenchSourceIndex(config.roots)
        self.overrides = _load_overrides(config.overrides_path)

    def disambiguate_batch(self, batch_artifact: Path) -> dict[str, Any]:
        batch = json.loads(batch_artifact.read_text(encoding="utf-8"))
        candidates = list(batch.get("selected") or [])
        results = [self.disambiguate_candidate(candidate) for candidate in candidates]
        selected = sum(1 for row in results if row.status in SELECTED_STATUSES)
        ambiguous = sum(
            1
            for row in results
            if row.status == DisambiguationStatus.AMBIGUOUS_NEEDS_OVERRIDE.value
        )
        unsafe = sum(
            1 for row in results if row.status == DisambiguationStatus.UNSAFE_ROOT_REJECTED.value
        )
        report = {
            "schema_version": "determinex-programbench-root-disambiguation-v1",
            "batch_id": "legacy_replay_promotion_batch_001",
            "source_batch": str(batch_artifact),
            "candidates": len(candidates),
            "selected": selected,
            "ambiguous": ambiguous,
            "unsafe_rejected": unsafe,
            "status_counts": _counts(row.status for row in results),
            "results": [asdict(row) for row in results],
            "policy": "Disambiguation selects canonical runnable roots only through deterministic precedence or evidence-backed manual override.",
        }
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    def disambiguate_candidate(self, candidate: dict[str, Any]) -> RootDisambiguationResult:
        tool = str(candidate.get("tool") or "")
        legacy_hash = str(candidate.get("legacy_row_hash") or "")
        base = RootDisambiguationResult(
            tool=tool,
            legacy_row_hash=legacy_hash,
            status=DisambiguationStatus.NO_RUNNABLE_ROOT.value,
            candidate_roots=0,
            evidence=[],
        )
        if not tool:
            base.reason = "missing_tool"
            return base

        override = self._try_override(tool, base)
        if override is not None:
            return override

        matches = self._matches_for_tool(tool)
        base.candidate_roots = len(matches)
        safe_matches = _filter_safe(matches, self.config.allowed_roots)
        if matches and not safe_matches:
            base.status = DisambiguationStatus.UNSAFE_ROOT_REJECTED.value
            base.reason = "all_matches_outside_allowed_roots"
            return base
        if not safe_matches:
            base.status = DisambiguationStatus.NO_RUNNABLE_ROOT.value
            base.reason = "no_runnable_root"
            return base

        scored = sorted(
            (_score_entry(entry, candidate) for entry in safe_matches),
            key=lambda row: (row["rank"], -row["score"], row["root"]),
        )
        best = scored[0]
        tied = [
            row for row in scored if row["rank"] == best["rank"] and row["score"] == best["score"]
        ]
        if len(tied) > 1:
            base.status = DisambiguationStatus.AMBIGUOUS_NEEDS_OVERRIDE.value
            base.reason = "multiple_equal_roots"
            base.candidate_roots = len(safe_matches)
            base.evidence = sorted({ev for row in tied for ev in row["evidence"]})
            return base
        return _selected(base, best)

    def _matches_for_tool(self, tool: str) -> list[ProgramBenchSourceEntry]:
        exact = self.index.find_exact(normalized_slug(tool))
        if exact:
            return _dedupe(exact)
        key = normalized_slug(tool)
        return _dedupe(self.index.find_by_key(key) + self.index.find_by_binary(key))

    def _try_override(
        self, tool: str, base: RootDisambiguationResult
    ) -> RootDisambiguationResult | None:
        override = _override_for(tool, self.overrides)
        if not override:
            return None
        root = Path(str(override.get("canonical_root") or ""))
        reason = str(override.get("reason") or "")
        evidence = override.get("evidence") or []
        if not root.exists():
            base.status = DisambiguationStatus.UNSAFE_ROOT_REJECTED.value
            base.reason = "override_root_missing"
            return base
        if not reason or not isinstance(evidence, list) or not evidence:
            base.status = DisambiguationStatus.UNSAFE_ROOT_REJECTED.value
            base.reason = "override_missing_reason_or_evidence"
            return base
        if not _inside_any(root, self.config.allowed_roots):
            base.status = DisambiguationStatus.UNSAFE_ROOT_REJECTED.value
            base.reason = "override_outside_allowed_roots"
            return base
        entry = _entry_for_root(root)
        row = {
            "entry": entry,
            "rank": 0,
            "score": 100,
            "root": entry.root,
            "status": DisambiguationStatus.OVERRIDE_ROOT_SELECTED.value,
            "method": "manual_override",
            "confidence": 0.99,
            "evidence": [
                "manual_override",
                *[str(item) for item in evidence],
                "inside_allowed_root",
            ],
        }
        return _selected(base, row)


def default_config(output_path: Path) -> RootDisambiguationConfig:
    roots = [
        Path("corpus/programbench/per_tool_overrides"),
        Path("corpus/programbench/locked"),
        Path("corpus/programbench/in_progress"),
        Path("T:/determinex-programbench"),
        Path("T:/Dev/ProgramBench"),
    ]
    return RootDisambiguationConfig(roots=roots, allowed_roots=roots, output_path=output_path)


def _score_entry(entry: ProgramBenchSourceEntry, candidate: dict[str, Any]) -> dict[str, Any]:
    root = Path(entry.root)
    root_text = str(root).replace("\\", "/").lower()
    evidence = ["matching_tool_slug", "inside_allowed_root"]
    rank = 7
    status = DisambiguationStatus.AMBIGUOUS_NEEDS_OVERRIDE.value
    method = "historical_or_unknown_root"
    if "corpus/programbench/per_tool_overrides" in root_text:
        rank = 1
        status = DisambiguationStatus.CANONICAL_ROOT_SELECTED.value
        method = "per_tool_overrides_precedence"
        evidence.append("per_tool_override_root")
    elif "corpus/programbench/locked" in root_text:
        rank = 2
        status = DisambiguationStatus.LOCKED_ROOT_SELECTED.value
        method = "locked_root_precedence"
        evidence.append("locked_root")
    elif "corpus/programbench/in_progress" in root_text:
        rank = 3
        status = DisambiguationStatus.ACTIVE_RUN_ROOT_SELECTED.value
        method = "active_in_progress_root"
        evidence.append("active_in_progress_root")
    elif "determinex-programbench" in root_text:
        if _manifest_matches(entry, candidate):
            rank = 4
            status = DisambiguationStatus.T_DRIVE_RUN_ROOT_SELECTED.value
            method = "t_drive_manifest_match"
            evidence.append("matching_shard_or_manifest")
        else:
            rank = 8
            evidence.append("t_drive_without_manifest_match")
    if _has_eval_harness(root):
        evidence.append("eval_harness_present")
    if _has_candidate_manifest(root):
        evidence.append("candidate_manifest_present")
    if _has_expected_source_or_binary(root):
        evidence.append("expected_binary_or_source_present")
    return {
        "entry": entry,
        "rank": rank,
        "score": len(evidence),
        "root": str(root),
        "status": status,
        "method": method,
        "confidence": _confidence(rank, len(evidence)),
        "evidence": evidence,
    }


def _selected(base: RootDisambiguationResult, row: dict[str, Any]) -> RootDisambiguationResult:
    entry: ProgramBenchSourceEntry = row["entry"]
    base.status = str(row["status"])
    base.selected_root = entry.root
    base.selected_source_root = entry.source_root
    base.confidence = float(row["confidence"])
    base.method = str(row["method"])
    base.evidence = list(row["evidence"])
    base.reason = "selected"
    if base.candidate_roots == 0:
        base.candidate_roots = 1
    return base


def _entry_for_root(root: Path) -> ProgramBenchSourceEntry:
    from corpus.legacy_recovery.programbench_source_index import (
        _entry_for,  # local helper, same package
    )

    return _entry_for(root)


def _load_overrides(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _override_for(tool: str, overrides: dict[str, Any]) -> dict[str, Any] | None:
    keys = [tool, normalized_slug(tool)]
    if "__" in tool:
        keys.append(tool.split("__", 1)[1].split(".", 1)[0])
    for key in keys:
        value = overrides.get(key)
        if isinstance(value, dict):
            return value
    return None


def _filter_safe(
    entries: list[ProgramBenchSourceEntry], allowed_roots: list[Path]
) -> list[ProgramBenchSourceEntry]:
    return [
        entry
        for entry in entries
        if _inside_any(Path(entry.root), allowed_roots)
        and _inside_any(Path(entry.source_root), allowed_roots)
    ]


def _inside_any(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
        if path.is_symlink():
            return False
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


def _dedupe(entries: list[ProgramBenchSourceEntry]) -> list[ProgramBenchSourceEntry]:
    seen: set[str] = set()
    out: list[ProgramBenchSourceEntry] = []
    for entry in entries:
        key = str(Path(entry.root).resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _has_eval_harness(root: Path) -> bool:
    return (
        (root / "eval").is_dir()
        or (root / "manifest.json").is_file()
        or (root / "gate_result.json").is_file()
    )


def _has_candidate_manifest(root: Path) -> bool:
    return any(
        (root / name).is_file()
        for name in ("manifest.json", "gate_result.json", "candidate_manifest.json")
    )


def _has_expected_source_or_binary(root: Path) -> bool:
    return (
        (root / "source").is_dir()
        or (root / "executable").is_file()
        or any(
            (root / name).is_file() for name in ("Cargo.toml", "go.mod", "package.json", "Makefile")
        )
    )


def _manifest_matches(entry: ProgramBenchSourceEntry, candidate: dict[str, Any]) -> bool:
    shard = str(candidate.get("shard_id") or candidate.get("run_id") or "")
    if not shard:
        return False
    return shard in json.dumps(entry.metadata, sort_keys=True)


def _confidence(rank: int, evidence_count: int) -> float:
    base = max(0.5, 1.0 - (rank * 0.08))
    return round(min(0.99, base + min(evidence_count, 5) * 0.01), 2)


def _counts(statuses) -> dict[str, int]:
    out: dict[str, int] = {}
    for status in statuses:
        out[status] = out.get(status, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select canonical ProgramBench roots from ambiguous resolver candidates."
    )
    parser.add_argument("batch_artifact", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/programbench_root_disambiguation_batch_001.json"),
    )
    parser.add_argument("--root", action="append", type=Path, default=None)
    parser.add_argument(
        "--overrides", type=Path, default=Path("assurance/config/programbench_root_overrides.json")
    )
    args = parser.parse_args()

    config = default_config(args.output)
    if args.root is not None:
        config.roots = args.root
        config.allowed_roots = args.root
    config.overrides_path = args.overrides
    report = ProgramBenchRootDisambiguator(config).disambiguate_batch(args.batch_artifact)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
