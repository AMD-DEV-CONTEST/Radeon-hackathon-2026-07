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

from corpus.programbench.cleanroom_build_recipe_provenance_gap_record import (
    verify_cleanroom_build_recipe_provenance_gap_record,
)
from corpus.programbench.cleanroom_build_recipe_recovery_record import (
    verify_cleanroom_build_recipe_recovery_record,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (
    verify_cleanroom_image_remediation_plan_record,
)
from corpus.programbench.cleanroom_recipe_provenance_recovery_record import (
    verify_cleanroom_recipe_provenance_recovery_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (
    make_rebuild_provenance_quarantine_decision_record,
    write_rebuild_provenance_quarantine_decision_record,
)


class RebuildProvenanceQuarantineDecisionStatus(str, Enum):
    REBUILD_QUARANTINE_DECISION_READY = "REBUILD_QUARANTINE_DECISION_READY"
    REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY = "REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY"
    REBUILD_QUARANTINE_DECISION_BLOCKED = "REBUILD_QUARANTINE_DECISION_BLOCKED"
    REBUILD_QUARANTINE_DECISION_BLOCKED_NO_RECOVERY = (
        "REBUILD_QUARANTINE_DECISION_BLOCKED_NO_RECOVERY"
    )
    REBUILD_QUARANTINE_DECISION_BLOCKED_IMAGE_MISMATCH = (
        "REBUILD_QUARANTINE_DECISION_BLOCKED_IMAGE_MISMATCH"
    )
    REBUILD_QUARANTINE_DECISION_BLOCKED_DIGEST_MISMATCH = (
        "REBUILD_QUARANTINE_DECISION_BLOCKED_DIGEST_MISMATCH"
    )
    REBUILD_QUARANTINE_DECISION_BLOCKED_CHAIN_INVALID = (
        "REBUILD_QUARANTINE_DECISION_BLOCKED_CHAIN_INVALID"
    )
    REMEDIATION_TECHNICALLY_AVAILABLE = "REMEDIATION_TECHNICALLY_AVAILABLE"
    REBUILD_PROVENANCE_AUTHORIZED = "REBUILD_PROVENANCE_AUTHORIZED"
    REBUILD_PROVENANCE_NOT_AUTHORIZED = "REBUILD_PROVENANCE_NOT_AUTHORIZED"
    ORIGINAL_RECIPE_GAP_OPEN = "ORIGINAL_RECIPE_GAP_OPEN"
    PINNED_BASE_IMAGE_DIGEST_GAP_OPEN = "PINNED_BASE_IMAGE_DIGEST_GAP_OPEN"
    MATERIAL_FIDELITY_CHANGE_CANDIDATE = "MATERIAL_FIDELITY_CHANGE_CANDIDATE"
    HYDRATION_NOT_AUTHORIZED = "HYDRATION_NOT_AUTHORIZED"
    PROGRAMBENCH_RERUN_NOT_AUTHORIZED = "PROGRAMBENCH_RERUN_NOT_AUTHORIZED"
    DOCKER_EXECUTION_NOT_AUTHORIZED = "DOCKER_EXECUTION_NOT_AUTHORIZED"
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    EXECUTABLE_FALSE = "EXECUTABLE_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class RebuildProvenanceQuarantineDecisionConfig:
    root: Path = Path(".")
    output_dir: Path = Path(
        "assurance/evidence/programbench_rebuild_provenance_quarantine_decisions"
    )
    target_image: str = ""
    target_digest: str = ""


class ProgramBenchRebuildProvenanceQuarantineDecision:
    def __init__(self, config: RebuildProvenanceQuarantineDecisionConfig | None = None) -> None:
        self.config = config or RebuildProvenanceQuarantineDecisionConfig()

    def decide(self, recipe_provenance_recovery_path: Path) -> dict[str, Any]:
        recovery_path = self._resolve(recipe_provenance_recovery_path)
        recovery = _read_json(recovery_path) if recovery_path.is_file() else {}
        if not recovery_path.is_file() or not verify_cleanroom_recipe_provenance_recovery_record(
            recovery
        ):
            return self._write_blocked(
                status=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_NO_RECOVERY.value,
                decision=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value,
                recovery_path=recovery_path,
                recovery=recovery,
                reasons=["recipe_provenance_recovery_missing_or_invalid"],
            )

        image = str(recovery.get("image_reference") or "")
        digest = str(recovery.get("image_digest") or "")
        if self.config.target_image and image != self.config.target_image:
            return self._write_blocked(
                status=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_IMAGE_MISMATCH.value,
                decision=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value,
                recovery_path=recovery_path,
                recovery=recovery,
                reasons=["image_reference_mismatch"],
            )
        if self.config.target_digest and digest != self.config.target_digest:
            return self._write_blocked(
                status=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_DIGEST_MISMATCH.value,
                decision=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value,
                recovery_path=recovery_path,
                recovery=recovery,
                reasons=["image_digest_mismatch"],
            )

        chain_valid, chain_reasons = self._validate_chain(recovery)
        if not chain_valid:
            return self._write_blocked(
                status=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_CHAIN_INVALID.value,
                decision=RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value,
                recovery_path=recovery_path,
                recovery=recovery,
                reasons=chain_reasons,
            )

        gap_closure = (
            recovery.get("gap_closure") if isinstance(recovery.get("gap_closure"), dict) else {}
        )
        go = (
            recovery.get("go_remediation")
            if isinstance(recovery.get("go_remediation"), dict)
            else {}
        )
        fidelity = (
            recovery.get("fidelity_assessment")
            if isinstance(recovery.get("fidelity_assessment"), dict)
            else {}
        )
        original_closed = bool(gap_closure.get("original_cleanroom_build_recipe_closed"))
        base_closed = bool(gap_closure.get("pinned_base_image_digest_closed"))
        go_available = bool(
            gap_closure.get("go_runtime_update_plan_available")
            or go.get("compatible_with_recovered_recipe")
        )
        material_risk = bool(
            fidelity.get("material_change_requires_review")
            or str(fidelity.get("fidelity_risk") or "") == "material"
        )
        recovery_decision = str(recovery.get("decision") or "")

        status = self._decision_status(original_closed, base_closed, recovery_decision)
        decision_statuses = [
            status,
            RebuildProvenanceQuarantineDecisionStatus.REMEDIATION_TECHNICALLY_AVAILABLE.value
            if go_available
            else "REMEDIATION_TECHNICALLY_UNPROVEN",
            RebuildProvenanceQuarantineDecisionStatus.REBUILD_PROVENANCE_AUTHORIZED.value
            if original_closed and base_closed
            else RebuildProvenanceQuarantineDecisionStatus.REBUILD_PROVENANCE_NOT_AUTHORIZED.value,
            RebuildProvenanceQuarantineDecisionStatus.MATERIAL_FIDELITY_CHANGE_CANDIDATE.value
            if material_risk
            else "FIDELITY_RISK_UNKNOWN",
            RebuildProvenanceQuarantineDecisionStatus.HYDRATION_NOT_AUTHORIZED.value,
            RebuildProvenanceQuarantineDecisionStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
            RebuildProvenanceQuarantineDecisionStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
            RebuildProvenanceQuarantineDecisionStatus.CACHE_READY_FALSE.value,
            RebuildProvenanceQuarantineDecisionStatus.EXECUTABLE_FALSE.value,
            RebuildProvenanceQuarantineDecisionStatus.TRAINING_INELIGIBLE.value,
        ]
        if not original_closed:
            decision_statuses.append(
                RebuildProvenanceQuarantineDecisionStatus.ORIGINAL_RECIPE_GAP_OPEN.value
            )
        if not base_closed:
            decision_statuses.append(
                RebuildProvenanceQuarantineDecisionStatus.PINNED_BASE_IMAGE_DIGEST_GAP_OPEN.value
            )

        record = make_rebuild_provenance_quarantine_decision_record(
            status=status,
            decision=status,
            image_reference=image,
            image_digest=digest,
            recipe_provenance_recovery=_rel(self.config.root, recovery_path),
            remediation_plan=str(recovery.get("remediation_plan") or ""),
            recipe_recovery=str(recovery.get("recipe_recovery") or ""),
            provenance_gap=str(recovery.get("provenance_gap") or ""),
            decision_statuses=list(dict.fromkeys(decision_statuses)),
            findings={
                "original_recipe_gap_open": not original_closed,
                "pinned_base_image_digest_gap_open": not base_closed,
                "go_runtime_target": str(go.get("target_version") or "1.24.13"),
                "go_runtime_current": str(go.get("current_version") or ""),
                "go_runtime_remediation_path_available": go_available,
                "remediation_technically_possible": go_available,
                "rebuild_provenance_authorized": bool(original_closed and base_closed),
                "material_fidelity_change_candidate": material_risk,
                "partial_provenance_is_sufficient_for_rebuild": False
                if not (original_closed and base_closed)
                else True,
            },
            authorization=_authorization(rebuild_provenance_ready=original_closed and base_closed),
            required_next_evidence=_required_next_evidence(original_closed, base_closed),
            reasons=_decision_reasons(original_closed, base_closed, go_available, material_risk),
            cache_ready=False,
            executable=False,
        )
        path = write_rebuild_provenance_quarantine_decision_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _decision_status(
        self, original_closed: bool, base_closed: bool, recovery_decision: str
    ) -> str:
        if original_closed and base_closed:
            return RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_READY.value
        if recovery_decision == "REBUILD_PROVENANCE_BLOCKED":
            return (
                RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value
            )
        if original_closed or base_closed:
            return RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY.value
        return (
            RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY.value
        )

    def _validate_chain(self, recovery: dict[str, Any]) -> tuple[bool, list[str]]:
        errors: list[str] = []
        plan_path = self._resolve(Path(str(recovery.get("remediation_plan") or "")))
        recipe_path = self._resolve(Path(str(recovery.get("recipe_recovery") or "")))
        gap_path = self._resolve(Path(str(recovery.get("provenance_gap") or "")))
        plan = _read_json(plan_path) if plan_path.is_file() else {}
        recipe = _read_json(recipe_path) if recipe_path.is_file() else {}
        gap = _read_json(gap_path) if gap_path.is_file() else {}
        if not verify_cleanroom_image_remediation_plan_record(plan):
            errors.append("remediation_plan_missing_or_invalid")
        if not verify_cleanroom_build_recipe_recovery_record(recipe):
            errors.append("build_recipe_recovery_missing_or_invalid")
        if not verify_cleanroom_build_recipe_provenance_gap_record(gap):
            errors.append("provenance_gap_missing_or_invalid")
        image = str(recovery.get("image_reference") or "")
        digest = str(recovery.get("image_digest") or "")
        for name, record in (
            ("remediation_plan", plan),
            ("build_recipe_recovery", recipe),
            ("provenance_gap", gap),
        ):
            if record and str(record.get("image_reference") or "") != image:
                errors.append(f"{name}_image_mismatch")
            if record and str(record.get("image_digest") or "") != digest:
                errors.append(f"{name}_digest_mismatch")
        return not errors, errors

    def _write_blocked(
        self,
        *,
        status: str,
        decision: str,
        recovery_path: Path,
        recovery: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        image = str(recovery.get("image_reference") or self.config.target_image)
        digest = str(recovery.get("image_digest") or self.config.target_digest)
        record = make_rebuild_provenance_quarantine_decision_record(
            status=status,
            decision=decision,
            image_reference=image,
            image_digest=digest,
            recipe_provenance_recovery=_rel(self.config.root, recovery_path),
            remediation_plan=str(recovery.get("remediation_plan") or ""),
            recipe_recovery=str(recovery.get("recipe_recovery") or ""),
            provenance_gap=str(recovery.get("provenance_gap") or ""),
            decision_statuses=[
                status,
                RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value,
                RebuildProvenanceQuarantineDecisionStatus.REBUILD_PROVENANCE_NOT_AUTHORIZED.value,
                RebuildProvenanceQuarantineDecisionStatus.HYDRATION_NOT_AUTHORIZED.value,
                RebuildProvenanceQuarantineDecisionStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
                RebuildProvenanceQuarantineDecisionStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
                RebuildProvenanceQuarantineDecisionStatus.CACHE_READY_FALSE.value,
                RebuildProvenanceQuarantineDecisionStatus.EXECUTABLE_FALSE.value,
                RebuildProvenanceQuarantineDecisionStatus.TRAINING_INELIGIBLE.value,
            ],
            findings={
                "original_recipe_gap_open": True,
                "pinned_base_image_digest_gap_open": True,
                "rebuild_provenance_authorized": False,
                "remediation_technically_possible": False,
            },
            authorization=_authorization(rebuild_provenance_ready=False),
            required_next_evidence=["valid_signed_recipe_provenance_recovery"],
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_rebuild_provenance_quarantine_decision_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _authorization(*, rebuild_provenance_ready: bool) -> dict[str, bool]:
    return {
        "rebuild_provenance_ready": bool(rebuild_provenance_ready),
        "image_rebuild_authorized": False,
        "docker_pull_authorized": False,
        "docker_execution_authorized": False,
        "hydration_authorized": False,
        "programbench_rerun_authorized": False,
        "policy_exception_authorized": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _required_next_evidence(original_closed: bool, base_closed: bool) -> list[str]:
    needed: list[str] = []
    if not original_closed:
        needed.append("original_cleanroom_build_recipe")
    if not base_closed:
        needed.append("pinned_base_image_digest")
    if not needed:
        needed.extend(
            ["image_rebuild_provenance_lock", "remediated_scan_evidence", "hydration_policy_pass"]
        )
    return needed


def _decision_reasons(
    original_closed: bool, base_closed: bool, go_available: bool, material_risk: bool
) -> list[str]:
    reasons: list[str] = []
    if go_available:
        reasons.append("go_runtime_remediation_technically_available")
    if not original_closed:
        reasons.append("original_cleanroom_build_recipe_gap_remains_open")
    if not base_closed:
        reasons.append("pinned_base_image_digest_gap_remains_open")
    if material_risk:
        reasons.append("future_rebuild_is_material_fidelity_change_candidate")
    if not original_closed or not base_closed:
        reasons.append("partial_provenance_is_not_rebuild_authority")
    return reasons


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a ProgramBench rebuild provenance quarantine decision."
    )
    parser.add_argument("recipe_provenance_recovery", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_rebuild_provenance_quarantine_decisions"),
    )
    parser.add_argument("--target-image", default="")
    parser.add_argument("--target-digest", default="")
    args = parser.parse_args()
    result = ProgramBenchRebuildProvenanceQuarantineDecision(
        RebuildProvenanceQuarantineDecisionConfig(
            root=args.root,
            output_dir=args.output_dir,
            target_image=args.target_image,
            target_digest=args.target_digest,
        )
    ).decide(args.recipe_provenance_recovery)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
