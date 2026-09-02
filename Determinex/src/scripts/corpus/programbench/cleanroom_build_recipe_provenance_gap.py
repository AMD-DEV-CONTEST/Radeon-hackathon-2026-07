#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_build_recipe_provenance_gap_record import (
    make_cleanroom_build_recipe_provenance_gap_record,
    write_cleanroom_build_recipe_provenance_gap_record,
)
from corpus.programbench.cleanroom_build_recipe_recovery_record import (
    verify_cleanroom_build_recipe_recovery_record,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (
    verify_cleanroom_image_remediation_plan_record,
)


class BuildRecipeProvenanceGapStatus(str, Enum):
    BUILD_RECIPE_PROVENANCE_GAP_READY = "BUILD_RECIPE_PROVENANCE_GAP_READY"
    BUILD_RECIPE_PROVENANCE_GAP_WRITTEN = "BUILD_RECIPE_PROVENANCE_GAP_WRITTEN"
    BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_PLAN = "BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_PLAN"
    BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_RECOVERY = (
        "BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_RECOVERY"
    )
    BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_IMAGE_MISMATCH = (
        "BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_IMAGE_MISMATCH"
    )
    BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_DIGEST_MISMATCH = (
        "BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_DIGEST_MISMATCH"
    )
    ORIGINAL_RECIPE_MISSING = "ORIGINAL_RECIPE_MISSING"
    BASE_IMAGE_DIGEST_MISSING = "BASE_IMAGE_DIGEST_MISSING"
    RECONSTRUCTED_FROM_IMAGE_HISTORY_ONLY = "RECONSTRUCTED_FROM_IMAGE_HISTORY_ONLY"
    MATERIAL_FIDELITY_RISK = "MATERIAL_FIDELITY_RISK"
    REDACTION_INVARIANT_VERIFIED = "REDACTION_INVARIANT_VERIFIED"
    REDACTION_INVARIANT_FAILED = "REDACTION_INVARIANT_FAILED"
    REBUILD_NOT_AUTHORIZED = "REBUILD_NOT_AUTHORIZED"
    DOCKER_EXECUTION_NOT_AUTHORIZED = "DOCKER_EXECUTION_NOT_AUTHORIZED"
    HYDRATION_NOT_AUTHORIZED = "HYDRATION_NOT_AUTHORIZED"
    PROGRAMBENCH_RERUN_NOT_AUTHORIZED = "PROGRAMBENCH_RERUN_NOT_AUTHORIZED"
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class BuildRecipeProvenanceGapConfig:
    root: Path = Path(".")
    output_dir: Path = Path(
        "assurance/evidence/programbench_cleanroom_build_recipe_provenance_gaps"
    )
    target_image: str = ""
    target_digest: str = ""


class ProgramBenchCleanroomBuildRecipeProvenanceGap:
    def __init__(self, config: BuildRecipeProvenanceGapConfig | None = None) -> None:
        self.config = config or BuildRecipeProvenanceGapConfig()

    def write_gap(self, remediation_plan_path: Path, recipe_recovery_path: Path) -> dict[str, Any]:
        plan_path = self._resolve(remediation_plan_path)
        recovery_path = self._resolve(recipe_recovery_path)
        plan = _read_json(plan_path) if plan_path.is_file() else {}
        recovery = _read_json(recovery_path) if recovery_path.is_file() else {}
        if not plan_path.is_file() or not verify_cleanroom_image_remediation_plan_record(plan):
            return self._write_blocked(
                BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_PLAN.value,
                plan_path,
                recovery_path,
                plan,
                recovery,
                ["remediation_plan_missing_or_invalid"],
            )
        if not recovery_path.is_file() or not verify_cleanroom_build_recipe_recovery_record(
            recovery
        ):
            return self._write_blocked(
                BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_RECOVERY.value,
                plan_path,
                recovery_path,
                plan,
                recovery,
                ["recipe_recovery_missing_or_invalid"],
            )

        image = str(plan.get("image_reference") or "")
        digest = str(plan.get("image_digest") or "")
        if image != str(recovery.get("image_reference") or "") or (
            self.config.target_image and image != self.config.target_image
        ):
            return self._write_blocked(
                BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_IMAGE_MISMATCH.value,
                plan_path,
                recovery_path,
                plan,
                recovery,
                ["image_reference_mismatch"],
            )
        if digest != str(recovery.get("image_digest") or "") or (
            self.config.target_digest and digest != self.config.target_digest
        ):
            return self._write_blocked(
                BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_DIGEST_MISMATCH.value,
                plan_path,
                recovery_path,
                plan,
                recovery,
                ["image_digest_mismatch"],
            )

        components = (
            recovery.get("recipe_components")
            if isinstance(recovery.get("recipe_components"), dict)
            else {}
        )
        go_update = recovery.get("go_update") if isinstance(recovery.get("go_update"), dict) else {}
        fidelity = (
            recovery.get("fidelity_assessment")
            if isinstance(recovery.get("fidelity_assessment"), dict)
            else {}
        )
        redaction = _redaction_invariant(recovery)
        gap_statuses = [
            BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_READY.value,
            BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_WRITTEN.value,
            BuildRecipeProvenanceGapStatus.REBUILD_NOT_AUTHORIZED.value,
            BuildRecipeProvenanceGapStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
            BuildRecipeProvenanceGapStatus.HYDRATION_NOT_AUTHORIZED.value,
            BuildRecipeProvenanceGapStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
            BuildRecipeProvenanceGapStatus.CACHE_READY_FALSE.value,
            BuildRecipeProvenanceGapStatus.TRAINING_INELIGIBLE.value,
        ]
        missing = []
        if not bool(components.get("original_recipe_file_recovered")):
            gap_statuses.append(BuildRecipeProvenanceGapStatus.ORIGINAL_RECIPE_MISSING.value)
            missing.append(
                _missing_component(
                    "original_cleanroom_build_recipe",
                    "original Dockerfile/Containerfile or signed build script used to produce the cleanroom image",
                )
            )
        if not bool(components.get("base_image_digest_present")):
            gap_statuses.append(BuildRecipeProvenanceGapStatus.BASE_IMAGE_DIGEST_MISSING.value)
            missing.append(
                _missing_component(
                    "pinned_base_image_digest",
                    "base image reference pinned by digest plus source registry/provenance",
                )
            )
        if bool(components.get("reconstructed_from_image_history")) and not bool(
            components.get("original_recipe_file_recovered")
        ):
            gap_statuses.append(
                BuildRecipeProvenanceGapStatus.RECONSTRUCTED_FROM_IMAGE_HISTORY_ONLY.value
            )
            missing.append(
                _missing_component(
                    "non_history_recipe_source",
                    "independent recipe source, not only OCI config history",
                )
            )
        if str(fidelity.get("fidelity_class") or "") == "material_fidelity_change":
            gap_statuses.append(BuildRecipeProvenanceGapStatus.MATERIAL_FIDELITY_RISK.value)
        gap_statuses.append(
            BuildRecipeProvenanceGapStatus.REDACTION_INVARIANT_VERIFIED.value
            if redaction["redaction_passed"]
            else BuildRecipeProvenanceGapStatus.REDACTION_INVARIANT_FAILED.value
        )
        record = make_cleanroom_build_recipe_provenance_gap_record(
            status=BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_WRITTEN.value,
            image_reference=image,
            image_digest=digest,
            remediation_plan=_rel(self.config.root, plan_path),
            recipe_recovery=_rel(self.config.root, recovery_path),
            gap_statuses=list(dict.fromkeys(gap_statuses)),
            missing_provenance_components=missing,
            closure_requirements=_closure_requirements(missing, go_update),
            observed_recipe_state={
                "original_recipe_file_recovered": bool(
                    components.get("original_recipe_file_recovered")
                ),
                "base_image_digest_present": bool(components.get("base_image_digest_present")),
                "reconstructed_recipe_source": "OCI config history only"
                if components.get("reconstructed_from_image_history")
                else "none",
                "go_current_version": str(go_update.get("current_version_detected") or ""),
                "go_target_version": str(go_update.get("target_version") or "1.24.13"),
                "go_update_compatible": bool(go_update.get("recipe_compatible")),
                "fidelity_risk": str(fidelity.get("fidelity_class") or ""),
            },
            redaction_invariant=redaction,
            authorization=_authorization(),
            reasons=[
                "oci_history_explains_probable_steps_but_is_not_original_recipe",
                "base_image_digest_missing",
                "rebuild_requires_provenance_closure",
            ],
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_build_recipe_provenance_gap_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _write_blocked(
        self,
        status: str,
        plan_path: Path,
        recovery_path: Path,
        plan: dict[str, Any],
        recovery: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        record = make_cleanroom_build_recipe_provenance_gap_record(
            status=status,
            image_reference=str(
                plan.get("image_reference")
                or recovery.get("image_reference")
                or self.config.target_image
            ),
            image_digest=str(
                plan.get("image_digest")
                or recovery.get("image_digest")
                or self.config.target_digest
            ),
            remediation_plan=_rel(self.config.root, plan_path),
            recipe_recovery=_rel(self.config.root, recovery_path),
            gap_statuses=[
                status,
                BuildRecipeProvenanceGapStatus.REBUILD_NOT_AUTHORIZED.value,
                BuildRecipeProvenanceGapStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
                BuildRecipeProvenanceGapStatus.HYDRATION_NOT_AUTHORIZED.value,
                BuildRecipeProvenanceGapStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
                BuildRecipeProvenanceGapStatus.CACHE_READY_FALSE.value,
                BuildRecipeProvenanceGapStatus.TRAINING_INELIGIBLE.value,
            ],
            authorization=_authorization(),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_build_recipe_provenance_gap_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _missing_component(component: str, requirement: str) -> dict[str, Any]:
    return {
        "component": component,
        "present": False,
        "required_to_close_gap": requirement,
        "accepted_evidence": [
            "signed internal build recipe record",
            "original ProgramBench Dockerfile or Containerfile with digest-pinned FROM",
            "operator-admitted recipe provenance linked to image digest",
        ],
    }


def _closure_requirements(
    missing: list[dict[str, Any]], go_update: dict[str, Any]
) -> list[dict[str, Any]]:
    requirements = [
        {
            "requirement": item["component"],
            "must_supply": item["required_to_close_gap"],
            "before": "PROGRAMBENCH_CLEANROOM_IMAGE_REBUILD_PROVENANCE_LOCK_001",
        }
        for item in missing
    ]
    requirements.append(
        {
            "requirement": "go_runtime_update_plan",
            "must_supply": f"replace Go {go_update.get('current_version_detected', '')} with {go_update.get('target_version', '1.24.13')} and rerun scan/hydration/bounded-rerun validation",
            "before": "any rebuilt image execution",
        }
    )
    return requirements


def _redaction_invariant(recovery: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(recovery.get("image_config_metadata") or {}, sort_keys=True)
    leaked = sorted(set(re.findall(r"ghp_[A-Za-z0-9_]{8,}", raw)))
    return {
        "checked": True,
        "redaction_passed": not leaked,
        "unredacted_token_count": len(leaked),
        "forbidden_patterns": ["ghp_*", "https://user:token@"],
    }


def _authorization() -> dict[str, bool]:
    return {
        "rebuild_authorized": False,
        "docker_pull_authorized": False,
        "docker_execution_authorized": False,
        "hydration_authorized": False,
        "programbench_rerun_authorized": False,
        "policy_exception_authorized": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except OSError:
        return {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a ProgramBench cleanroom build recipe provenance-gap packet."
    )
    parser.add_argument("remediation_plan", type=Path)
    parser.add_argument("recipe_recovery", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_build_recipe_provenance_gaps"),
    )
    parser.add_argument("--target-image", default="")
    parser.add_argument("--target-digest", default="")
    args = parser.parse_args()
    result = ProgramBenchCleanroomBuildRecipeProvenanceGap(
        BuildRecipeProvenanceGapConfig(
            root=args.root,
            output_dir=args.output_dir,
            target_image=args.target_image,
            target_digest=args.target_digest,
        )
    ).write_gap(args.remediation_plan, args.recipe_recovery)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
