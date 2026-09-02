#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.programbench_image_locator import ProgramBenchImageLocator
from corpus.legacy_recovery.programbench_task_locator import ProgramBenchTaskLocator


class HydrationStatus(str, Enum):
    HYDRATED_READY = "HYDRATED_READY"
    MISSING_TASK_ROOT = "MISSING_TASK_ROOT"
    MISSING_CANDIDATE_ROOT = "MISSING_CANDIDATE_ROOT"
    MISSING_DOCKER_IMAGE = "MISSING_DOCKER_IMAGE"
    MISSING_EVAL_HARNESS = "MISSING_EVAL_HARNESS"
    MISSING_BASELINE = "MISSING_BASELINE"
    AMBIGUOUS_TOOL_MATCH = "AMBIGUOUS_TOOL_MATCH"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    UNSUPPORTED_LEGACY_FORMAT = "UNSUPPORTED_LEGACY_FORMAT"


@dataclass(slots=True)
class HydrationConfig:
    task_roots: list[Path]
    candidate_roots: list[Path]
    programbench_roots: list[Path]
    image_roots: list[Path]
    output_path: Path = Path(
        "assurance/evidence/programbench_replay_batch_001_hydration_report.json"
    )
    resolution_report: Path | None = None
    disambiguation_report: Path | None = None
    require_image: bool = True
    require_baseline: bool = False


@dataclass(slots=True)
class HydrationResult:
    tool: str
    status: str
    language_guess: str
    failure_class: str
    legacy_row_hash: str
    duplicate_cluster_id: str
    task_root: str = ""
    candidate_root: str = ""
    task_image: str = ""
    baseline_artifact: str = ""
    eval_command: str = ""
    expected_result_path: str = ""
    workspace_checksum: str = ""
    reason: str = ""


class ProgramBenchReplayHydrator:
    def __init__(self, config: HydrationConfig) -> None:
        self.config = config
        self.task_locator = ProgramBenchTaskLocator(config.task_roots)
        self.candidate_locator = ProgramBenchTaskLocator(config.candidate_roots)
        self.image_locator = ProgramBenchImageLocator(
            config.image_roots, require_image=config.require_image
        )
        self.resolutions = _load_resolutions(config.resolution_report)
        self.disambiguations = _load_selected_disambiguations(config.disambiguation_report)

    def hydrate_batch(self, batch_artifact: Path) -> dict[str, Any]:
        batch = json.loads(batch_artifact.read_text(encoding="utf-8"))
        candidates = list(batch.get("selected") or [])
        results = [self.hydrate_candidate(candidate) for candidate in candidates]
        counts: dict[str, int] = {status.value: 0 for status in HydrationStatus}
        for result in results:
            counts[result.status] += 1
        report = {
            "schema_version": "determinex-programbench-replay-hydration-v1",
            "batch_id": "legacy_replay_promotion_batch_001",
            "source_batch": str(batch_artifact),
            "candidates": len(candidates),
            "status_counts": {k: v for k, v in counts.items() if v},
            "hydrated_ready": counts[HydrationStatus.HYDRATED_READY.value],
            "results": [asdict(result) for result in results],
            "policy": "Hydration only locates runnable context. It does not run verifier or promote rows.",
        }
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    def hydrate_candidate(self, candidate: dict[str, Any]) -> HydrationResult:
        base = _base_result(candidate)
        if not base.tool or not base.legacy_row_hash:
            base.status = HydrationStatus.UNSUPPORTED_LEGACY_FORMAT.value
            base.reason = "missing_tool_or_legacy_row_hash"
            return base

        disambiguated = self.disambiguations.get(base.tool)
        if disambiguated:
            base.task_root = str(disambiguated.get("selected_root") or "")
            base.candidate_root = str(disambiguated.get("selected_root") or "")
            if not base.task_root or not Path(base.task_root).exists():
                return _with_status(
                    base, HydrationStatus.MISSING_TASK_ROOT, "disambiguated_task_root_missing"
                )
            task_path = Path(base.task_root)
            return self._finish_hydration(candidate, base, task_path, task_path)

        resolved = self.resolutions.get(base.tool)
        if resolved and resolved.get("resolution_status") == "TASK_AND_SOURCE_RESOLVED":
            base.task_root = str(resolved.get("task_root") or "")
            base.candidate_root = str(
                resolved.get("candidate_root") or resolved.get("task_root") or ""
            )
            if not base.task_root or not Path(base.task_root).exists():
                return _with_status(
                    base, HydrationStatus.MISSING_TASK_ROOT, "resolved_task_root_missing"
                )
            if not base.candidate_root or not Path(base.candidate_root).exists():
                return _with_status(
                    base, HydrationStatus.MISSING_CANDIDATE_ROOT, "resolved_candidate_root_missing"
                )
            task_path = Path(base.task_root)
            candidate_path = Path(base.candidate_root)
            return self._finish_hydration(candidate, base, task_path, candidate_path)

        task = self.task_locator.locate(base.tool)
        if task.ambiguous:
            return _with_status(base, HydrationStatus.AMBIGUOUS_TOOL_MATCH, "ambiguous_task_root")
        if task.path is None:
            return _with_status(base, HydrationStatus.MISSING_TASK_ROOT, "task_root_not_found")
        base.task_root = str(task.path)

        candidate_root = self.candidate_locator.locate(base.tool)
        if candidate_root.ambiguous:
            return _with_status(
                base, HydrationStatus.AMBIGUOUS_TOOL_MATCH, "ambiguous_candidate_root"
            )
        if candidate_root.path is None:
            return _with_status(
                base, HydrationStatus.MISSING_CANDIDATE_ROOT, "candidate_root_not_found"
            )
        base.candidate_root = str(candidate_root.path)

        return self._finish_hydration(candidate, base, task.path, candidate_root.path)

    def _finish_hydration(
        self,
        candidate: dict[str, Any],
        base: HydrationResult,
        task_path: Path,
        candidate_path: Path,
    ) -> HydrationResult:
        harness = _locate_eval_harness(self.config.programbench_roots)
        if not harness:
            return _with_status(
                base, HydrationStatus.MISSING_EVAL_HARNESS, "programbench_eval_harness_not_found"
            )
        base.eval_command = f"uv run programbench eval {base.candidate_root} --filter {base.tool.split('__', 1)[0]} --force"

        image = self.image_locator.locate(candidate, task_path)
        base.task_image = image.image
        if not image.available:
            return _with_status(base, HydrationStatus.MISSING_DOCKER_IMAGE, image.reason)

        baseline = _locate_baseline(candidate, task_path, candidate_path)
        base.baseline_artifact = str(baseline) if baseline else ""
        if self.config.require_baseline and baseline is None:
            return _with_status(
                base, HydrationStatus.MISSING_BASELINE, "baseline_artifact_not_found"
            )

        base.expected_result_path = str(
            Path("assurance/evidence") / f"{_safe_name(base.tool)}_replay_eval.json"
        )
        base.workspace_checksum = _workspace_checksum(candidate_path)
        if (
            candidate.get("workspace_checksum")
            and candidate.get("workspace_checksum") != base.workspace_checksum
        ):
            return _with_status(
                base, HydrationStatus.CHECKSUM_MISMATCH, "workspace_checksum_mismatch"
            )

        base.status = HydrationStatus.HYDRATED_READY.value
        base.reason = "ready"
        return base


def default_config(output_path: Path) -> HydrationConfig:
    return HydrationConfig(
        task_roots=[
            Path("T:/determinex-programbench"),
            Path("T:/Dev/ProgramBench"),
        ],
        candidate_roots=[
            Path("corpus/programbench/per_tool_overrides"),
            Path("corpus/programbench/in_progress"),
            Path("corpus/programbench/locked"),
            Path("T:/determinex-programbench"),
        ],
        programbench_roots=[Path("T:/Dev/ProgramBench"), Path(".")],
        image_roots=[
            Path("T:/programbench-images"),
            Path("assurance/evidence/programbench_images"),
        ],
        output_path=output_path,
    )


def _base_result(candidate: dict[str, Any]) -> HydrationResult:
    classes = candidate.get("failure_classes") or ["unknown"]
    return HydrationResult(
        tool=str(candidate.get("tool") or ""),
        status=HydrationStatus.UNSUPPORTED_LEGACY_FORMAT.value,
        language_guess=str(candidate.get("language_guess") or "unknown"),
        failure_class=str(classes[0]),
        legacy_row_hash=str(candidate.get("legacy_row_hash") or ""),
        duplicate_cluster_id=str(candidate.get("duplicate_cluster_id") or ""),
    )


def _with_status(result: HydrationResult, status: HydrationStatus, reason: str) -> HydrationResult:
    result.status = status.value
    result.reason = reason
    return result


def _locate_eval_harness(roots: list[Path]) -> Path | None:
    for root in roots:
        if not root.exists():
            continue
        if (root / "pyproject.toml").is_file() or (root / "programbench").is_dir():
            return root
    return None


def _locate_baseline(
    candidate: dict[str, Any], task_root: Path, candidate_root: Path
) -> Path | None:
    for key in ("baseline_artifact", "baseline_eval", "baseline_path"):
        value = candidate.get(key)
        if value and Path(str(value)).exists():
            return Path(str(value))
    for root in (candidate_root, task_root):
        for name in ("baseline.json", "baseline_eval.json", "gate_baseline.json"):
            path = root / name
            if path.is_file():
                return path
    return None


def _workspace_checksum(root: Path) -> str:
    h = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or count >= 200:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        h.update(rel.encode("utf-8", "replace"))
        try:
            stat = path.stat()
        except OSError:
            continue
        h.update(str(stat.st_size).encode())
        count += 1
    return h.hexdigest()


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:120] or "unknown"


def _load_resolutions(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("results") or []:
        if isinstance(row, dict) and row.get("tool"):
            out[str(row["tool"])] = row
    return out


def _load_selected_disambiguations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    selected_statuses = {
        "CANONICAL_ROOT_SELECTED",
        "OVERRIDE_ROOT_SELECTED",
        "LOCKED_ROOT_SELECTED",
        "ACTIVE_RUN_ROOT_SELECTED",
        "T_DRIVE_RUN_ROOT_SELECTED",
    }
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("results") or []:
        if isinstance(row, dict) and row.get("tool") and row.get("status") in selected_statuses:
            out[str(row["tool"])] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight hydration for selected ProgramBench replay candidates."
    )
    parser.add_argument("batch_artifact", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/programbench_replay_batch_001_hydration_report.json"),
    )
    parser.add_argument("--task-root", action="append", type=Path, default=None)
    parser.add_argument("--candidate-root", action="append", type=Path, default=None)
    parser.add_argument("--programbench-root", action="append", type=Path, default=None)
    parser.add_argument("--image-root", action="append", type=Path, default=None)
    parser.add_argument("--resolution-report", type=Path, default=None)
    parser.add_argument("--disambiguation-report", type=Path, default=None)
    parser.add_argument("--no-image-required", action="store_true")
    parser.add_argument("--require-baseline", action="store_true")
    args = parser.parse_args()

    config = default_config(args.output)
    if args.task_root is not None:
        config.task_roots = args.task_root
    if args.candidate_root is not None:
        config.candidate_roots = args.candidate_root
    if args.programbench_root is not None:
        config.programbench_roots = args.programbench_root
    if args.image_root is not None:
        config.image_roots = args.image_root
    config.require_image = not args.no_image_required
    config.require_baseline = args.require_baseline
    config.resolution_report = args.resolution_report
    config.disambiguation_report = args.disambiguation_report

    report = ProgramBenchReplayHydrator(config).hydrate_batch(args.batch_artifact)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
