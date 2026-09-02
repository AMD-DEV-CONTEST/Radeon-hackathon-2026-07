#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_image_remediation_plan_record import (
    make_cleanroom_image_remediation_plan_record,
    write_cleanroom_image_remediation_plan_record,
)
from corpus.programbench.cleanroom_image_scan_record import verify_cleanroom_image_scan_record
from corpus.programbench.cleanroom_image_scan_triage_record import (
    verify_cleanroom_image_scan_triage_record,
)


class CleanroomImageRemediationPlanStatus(str, Enum):
    CLEANROOM_IMAGE_REMEDIATION_PLAN_READY = "CLEANROOM_IMAGE_REMEDIATION_PLAN_READY"
    CLEANROOM_IMAGE_REMEDIATION_REQUIRED = "CLEANROOM_IMAGE_REMEDIATION_REQUIRED"
    CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN = "CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN"
    CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BUILD_RECIPE = (
        "CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BUILD_RECIPE"
    )
    CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BASE_PROVENANCE = (
        "CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BASE_PROVENANCE"
    )
    CLEANROOM_IMAGE_REMEDIATION_REQUIRES_RUNTIME_UPDATE = (
        "CLEANROOM_IMAGE_REMEDIATION_REQUIRES_RUNTIME_UPDATE"
    )
    CLEANROOM_IMAGE_REMEDIATION_FIDELITY_RISK = "CLEANROOM_IMAGE_REMEDIATION_FIDELITY_RISK"
    CLEANROOM_IMAGE_SAFER_EQUIVALENT_REQUIRED = "CLEANROOM_IMAGE_SAFER_EQUIVALENT_REQUIRED"
    CLEANROOM_IMAGE_POLICY_STILL_BLOCKED = "CLEANROOM_IMAGE_POLICY_STILL_BLOCKED"
    CLEANROOM_IMAGE_NOT_EXECUTABLE = "CLEANROOM_IMAGE_NOT_EXECUTABLE"
    CLEANROOM_IMAGE_TRAINING_INELIGIBLE = "CLEANROOM_IMAGE_TRAINING_INELIGIBLE"
    CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_SCAN = (
        "CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_SCAN"
    )
    CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_TRIAGE = (
        "CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_TRIAGE"
    )
    CLEANROOM_IMAGE_REMEDIATION_PLAN_NOT_REQUIRED = "CLEANROOM_IMAGE_REMEDIATION_PLAN_NOT_REQUIRED"


@dataclass(slots=True)
class CleanroomImageRemediationPlanConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_image_remediation_plans")
    build_recipe: Path | None = None
    base_image_digest: str = ""
    go_version_target: str = "1.24.13"


class ProgramBenchCleanroomImageRemediationPlan:
    def __init__(self, config: CleanroomImageRemediationPlanConfig | None = None) -> None:
        self.config = config or CleanroomImageRemediationPlanConfig()

    def plan(self, scan_record_path: Path, triage_record_path: Path) -> dict[str, Any]:
        scan_path = self._resolve(scan_record_path)
        triage_path = self._resolve(triage_record_path)
        if not scan_path.is_file():
            return self._blocked(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_SCAN.value,
                scan_path,
                triage_path,
                {},
                {},
                ["scan_evidence_missing"],
            )
        if not triage_path.is_file():
            return self._blocked(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_TRIAGE.value,
                scan_path,
                triage_path,
                _read_json(scan_path),
                {},
                ["triage_evidence_missing"],
            )
        scan = _read_json(scan_path)
        triage = _read_json(triage_path)
        if not verify_cleanroom_image_scan_record(scan):
            return self._blocked(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_SCAN.value,
                scan_path,
                triage_path,
                scan,
                triage,
                ["scan_evidence_signature_invalid"],
            )
        if not verify_cleanroom_image_scan_triage_record(triage):
            return self._blocked(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_TRIAGE.value,
                scan_path,
                triage_path,
                scan,
                triage,
                ["triage_evidence_signature_invalid"],
            )
        if str(triage.get("recommendation") or "") != "REMEDIATE_IMAGE_REQUIRED":
            return self._write(
                status=CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_NOT_REQUIRED.value,
                scan_path=scan_path,
                triage_path=triage_path,
                scan=scan,
                triage=triage,
                recommendation=str(triage.get("recommendation") or "SCAN_DATA_INSUFFICIENT"),
                strategies=[],
                required_inputs={},
                ordered_steps=[],
                fidelity_risk={"risk": "none", "reason": "triage_does_not_require_remediation"},
                statuses=[
                    CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_POLICY_STILL_BLOCKED.value,
                ],
                reasons=["triage_recommendation_not_remediate"],
            )
        policy_unblocked = not bool(triage.get("policy_blocked", True))
        if policy_unblocked:
            return self._write(
                status=CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_NOT_REQUIRED.value,
                scan_path=scan_path,
                triage_path=triage_path,
                scan=scan,
                triage=triage,
                recommendation="NO_REMEDIATION_REQUIRED",
                strategies=[],
                required_inputs={},
                ordered_steps=[],
                fidelity_risk={"risk": "none", "reason": "policy_not_blocked"},
                statuses=[],
                reasons=["policy_not_blocked"],
            )

        dominant = str((triage.get("category_summary") or {}).get("dominant_category") or "unknown")
        top_drivers = _top_drivers(triage)
        required_inputs = {
            "source_dockerfile_or_build_recipe": str(self.config.build_recipe or ""),
            "source_dockerfile_or_build_recipe_required": self.config.build_recipe is None,
            "base_image_digest": self.config.base_image_digest,
            "base_image_digest_required": not bool(self.config.base_image_digest),
            "go_version_target": self.config.go_version_target,
            "expected_digest_after_rebuild": "unknown_until_rebuild",
            "scanner_rerun_required": True,
            "hydration_policy_rerun_required": True,
            "bounded_rerun_revalidation_required": True,
        }
        strategies = _strategies(dominant, self.config.go_version_target)
        statuses = [
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_READY.value,
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_REQUIRED.value,
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN.value,
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_POLICY_STILL_BLOCKED.value,
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_FIDELITY_RISK.value,
        ]
        if dominant == "language_runtime":
            statuses.append(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_REQUIRES_RUNTIME_UPDATE.value
            )
        if required_inputs["source_dockerfile_or_build_recipe_required"]:
            statuses.append(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BUILD_RECIPE.value
            )
        if required_inputs["base_image_digest_required"]:
            statuses.append(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BASE_PROVENANCE.value
            )
        if (triage.get("fixed_version_summary") or {}).get("critical_high_without_fix", 0):
            statuses.append(
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_SAFER_EQUIVALENT_REQUIRED.value
            )
        return self._write(
            status=CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN.value,
            scan_path=scan_path,
            triage_path=triage_path,
            scan=scan,
            triage=triage,
            recommendation="REMEDIATE_IMAGE_REQUIRED",
            strategies=strategies,
            required_inputs=required_inputs,
            ordered_steps=_ordered_steps(),
            fidelity_risk={
                "risk": "material",
                "reason": "Updating Go runtime or base image may change benchmark execution behavior.",
                "must_revalidate_with_bounded_rerun": True,
                "must_mark_digest_changed": True,
            },
            statuses=statuses,
            reasons=["dominant_risk_requires_rebuild_plan", "no_policy_exception_created"],
            top_drivers=top_drivers,
        )

    def _blocked(
        self,
        status: str,
        scan_path: Path,
        triage_path: Path,
        scan: dict[str, Any],
        triage: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        return self._write(
            status=status,
            scan_path=scan_path,
            triage_path=triage_path,
            scan=scan,
            triage=triage,
            recommendation="SCAN_DATA_INSUFFICIENT",
            strategies=[],
            required_inputs={},
            ordered_steps=[],
            fidelity_risk={"risk": "unknown", "reason": "required_evidence_missing"},
            statuses=[
                status,
                CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_POLICY_STILL_BLOCKED.value,
            ],
            reasons=reasons,
        )

    def _write(
        self,
        *,
        status: str,
        scan_path: Path,
        triage_path: Path,
        scan: dict[str, Any],
        triage: dict[str, Any],
        recommendation: str,
        strategies: list[dict[str, Any]],
        required_inputs: dict[str, Any],
        ordered_steps: list[str],
        fidelity_risk: dict[str, Any],
        statuses: list[str],
        reasons: list[str],
        top_drivers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        statuses = [
            *statuses,
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_TRAINING_INELIGIBLE.value,
        ]
        record = make_cleanroom_image_remediation_plan_record(
            status=status,
            image_reference=str(scan.get("image_reference") or triage.get("image_reference") or ""),
            image_digest=str(scan.get("observed_digest") or triage.get("observed_digest") or ""),
            scan_record=_rel(self.config.root, scan_path),
            triage_record=_rel(self.config.root, triage_path),
            recommendation=recommendation,
            dominant_risk_category=str(
                (triage.get("category_summary") or {}).get("dominant_category") or ""
            ),
            severity_counts=triage.get("severity_counts")
            if isinstance(triage.get("severity_counts"), dict)
            else {},
            fixed_version_summary=triage.get("fixed_version_summary")
            if isinstance(triage.get("fixed_version_summary"), dict)
            else {},
            top_drivers=top_drivers or [],
            remediation_strategies=strategies,
            required_inputs=required_inputs,
            ordered_steps=ordered_steps,
            fidelity_risk=fidelity_risk,
            plan_statuses=list(dict.fromkeys(statuses)),
            reasons=reasons,
            policy_blocked=True,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_remediation_plan_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _top_drivers(triage: dict[str, Any]) -> list[dict[str, Any]]:
    drivers: list[dict[str, Any]] = []
    for item in (triage.get("top_critical") or []) + (triage.get("top_high") or []):
        if isinstance(item, dict):
            drivers.append(
                {
                    "id": item.get("id", ""),
                    "package": item.get("package", ""),
                    "installed_version": item.get("installed_version", ""),
                    "fixed_version": item.get("fixed_version", ""),
                    "severity": item.get("severity", ""),
                    "count": item.get("count", 0),
                    "category": item.get("category", ""),
                }
            )
    return drivers[:12]


def _strategies(dominant: str, go_version_target: str) -> list[dict[str, Any]]:
    strategies = [
        {
            "strategy": "update_go_runtime_toolchain",
            "priority": 1 if dominant == "language_runtime" else 2,
            "target_version": go_version_target,
            "rationale": "Critical/high findings are dominated by Go stdlib/runtime vulnerabilities.",
            "execution_allowed_by_this_lock": False,
        },
        {
            "strategy": "rebuild_same_base_with_patched_runtime",
            "priority": 2,
            "rationale": "Preserves base image shape while replacing vulnerable language runtime if build recipe supports it.",
            "execution_allowed_by_this_lock": False,
        },
        {
            "strategy": "rebuild_newer_base_preserving_benchmark_requirements",
            "priority": 3,
            "rationale": "May reduce OS/base findings but carries higher benchmark-fidelity risk.",
            "execution_allowed_by_this_lock": False,
        },
        {
            "strategy": "locate_safer_equivalent_upstream_cleanroom_image",
            "priority": 4,
            "rationale": "Requires exact provenance and digest admission before use.",
            "execution_allowed_by_this_lock": False,
        },
    ]
    return sorted(strategies, key=lambda item: int(item["priority"]))


def _ordered_steps() -> list[str]:
    return [
        "Recover or verify the original ProgramBench cleanroom image build recipe.",
        "Recover or verify the original base image digest and source provenance.",
        "Patch the language runtime/toolchain to a fixed Go version while preserving benchmark task requirements.",
        "If same-base remediation is impossible, identify a safer equivalent image or newer base with signed provenance.",
        "Build only under a later explicit rebuild provenance lock.",
        "Import rebuilt artifact by digest into quarantine.",
        "Rerun admitted scanner against rebuilt artifact.",
        "Rerun cleanroom hydration policy after scan evidence passes.",
        "Revalidate the bounded Doxygen rerun before execution.",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan remediation for a failed ProgramBench cleanroom image scan."
    )
    parser.add_argument("scan_record", type=Path)
    parser.add_argument("triage_record", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_remediation_plans"),
    )
    parser.add_argument("--build-recipe", type=Path)
    parser.add_argument("--base-image-digest", default="")
    parser.add_argument("--go-version-target", default="1.24.13")
    args = parser.parse_args()
    result = ProgramBenchCleanroomImageRemediationPlan(
        CleanroomImageRemediationPlanConfig(
            root=args.root,
            output_dir=args.output_dir,
            build_recipe=args.build_recipe,
            base_image_digest=args.base_image_digest,
            go_version_target=args.go_version_target,
        )
    ).plan(args.scan_record, args.triage_record)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
