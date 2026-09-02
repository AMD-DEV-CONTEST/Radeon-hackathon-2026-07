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
from corpus.programbench.operator_provenance_request_packet_record import (
    make_operator_provenance_request_packet_record,
    write_operator_provenance_request_packet_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (
    verify_rebuild_provenance_quarantine_decision_record,
)


class OperatorProvenanceRequestPacketStatus(str, Enum):
    OPERATOR_PROVENANCE_REQUEST_PACKET_READY = "OPERATOR_PROVENANCE_REQUEST_PACKET_READY"
    OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN = "OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN"
    OPERATOR_PROVENANCE_REQUEST_BLOCKED_NO_DECISION = (
        "OPERATOR_PROVENANCE_REQUEST_BLOCKED_NO_DECISION"
    )
    OPERATOR_PROVENANCE_REQUEST_BLOCKED_IMAGE_MISMATCH = (
        "OPERATOR_PROVENANCE_REQUEST_BLOCKED_IMAGE_MISMATCH"
    )
    OPERATOR_PROVENANCE_REQUEST_BLOCKED_DIGEST_MISMATCH = (
        "OPERATOR_PROVENANCE_REQUEST_BLOCKED_DIGEST_MISMATCH"
    )
    OPERATOR_PROVENANCE_REQUEST_BLOCKED_CHAIN_INVALID = (
        "OPERATOR_PROVENANCE_REQUEST_BLOCKED_CHAIN_INVALID"
    )
    ORIGINAL_RECIPE_PROVENANCE_REQUIRED = "ORIGINAL_RECIPE_PROVENANCE_REQUIRED"
    PINNED_BASE_IMAGE_DIGEST_REQUIRED = "PINNED_BASE_IMAGE_DIGEST_REQUIRED"
    ORIGINAL_BUILD_CONTEXT_REQUIRED = "ORIGINAL_BUILD_CONTEXT_REQUIRED"
    TOOLCHAIN_PROVENANCE_REQUIRED = "TOOLCHAIN_PROVENANCE_REQUIRED"
    GO_RUNTIME_ORIGINAL_CONFIRMATION_REQUIRED = "GO_RUNTIME_ORIGINAL_CONFIRMATION_REQUIRED"
    GO_REMEDIATION_TARGET_CONFIRMED = "GO_REMEDIATION_TARGET_CONFIRMED"
    MATERIAL_FIDELITY_RISK_DISCLOSED = "MATERIAL_FIDELITY_RISK_DISCLOSED"
    REBUILD_NOT_AUTHORIZED = "REBUILD_NOT_AUTHORIZED"
    DOCKER_PULL_NOT_AUTHORIZED = "DOCKER_PULL_NOT_AUTHORIZED"
    DOCKER_EXECUTION_NOT_AUTHORIZED = "DOCKER_EXECUTION_NOT_AUTHORIZED"
    HYDRATION_NOT_AUTHORIZED = "HYDRATION_NOT_AUTHORIZED"
    PROGRAMBENCH_RERUN_NOT_AUTHORIZED = "PROGRAMBENCH_RERUN_NOT_AUTHORIZED"
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    EXECUTABLE_FALSE = "EXECUTABLE_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class OperatorProvenanceRequestPacketConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_operator_provenance_requests")
    target_image: str = ""
    target_digest: str = ""


class ProgramBenchOperatorProvenanceRequestPacket:
    def __init__(self, config: OperatorProvenanceRequestPacketConfig | None = None) -> None:
        self.config = config or OperatorProvenanceRequestPacketConfig()

    def write_packet(self, rebuild_quarantine_decision_path: Path) -> dict[str, Any]:
        decision_path = self._resolve(rebuild_quarantine_decision_path)
        decision = _read_json(decision_path) if decision_path.is_file() else {}
        if not decision_path.is_file() or not verify_rebuild_provenance_quarantine_decision_record(
            decision
        ):
            return self._write_blocked(
                status=OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_NO_DECISION.value,
                decision_path=decision_path,
                decision=decision,
                reasons=["rebuild_quarantine_decision_missing_or_invalid"],
            )

        image = str(decision.get("image_reference") or "")
        digest = str(decision.get("image_digest") or "")
        if self.config.target_image and image != self.config.target_image:
            return self._write_blocked(
                status=OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_IMAGE_MISMATCH.value,
                decision_path=decision_path,
                decision=decision,
                reasons=["image_reference_mismatch"],
            )
        if self.config.target_digest and digest != self.config.target_digest:
            return self._write_blocked(
                status=OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_DIGEST_MISMATCH.value,
                decision_path=decision_path,
                decision=decision,
                reasons=["image_digest_mismatch"],
            )

        chain, errors = self._load_and_validate_chain(decision)
        if errors:
            return self._write_blocked(
                status=OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_CHAIN_INVALID.value,
                decision_path=decision_path,
                decision=decision,
                reasons=errors,
            )

        findings = decision.get("findings") if isinstance(decision.get("findings"), dict) else {}
        current_go = str(findings.get("go_runtime_current") or "1.21.0")
        target_go = str(findings.get("go_runtime_target") or "1.24.13")
        original_gap_open = bool(findings.get("original_recipe_gap_open", True))
        base_gap_open = bool(findings.get("pinned_base_image_digest_gap_open", True))
        material_risk = bool(findings.get("material_fidelity_change_candidate", True))

        missing = _missing_evidence(
            original_gap_open=original_gap_open, base_gap_open=base_gap_open
        )
        record = make_operator_provenance_request_packet_record(
            status=OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN.value,
            image_reference=image,
            image_digest=digest,
            rebuild_quarantine_decision=_rel(self.config.root, decision_path),
            current_decision=str(decision.get("decision") or decision.get("status") or ""),
            required_evidence=_required_evidence(current_go=current_go, target_go=target_go),
            missing_evidence=missing,
            acceptance_criteria=_acceptance_criteria(),
            acceptable_provenance_forms=_acceptable_forms(),
            unacceptable_provenance_forms=_unacceptable_forms(),
            operator_admission_checklist=_operator_checklist(),
            toolchain_requirements={
                "original_go_runtime_confirmation_required": True,
                "original_go_runtime_expected": current_go,
                "remediation_target_go_runtime": target_go,
                "toolchain_source_and_digest_required": True,
            },
            benchmark_fidelity_impact={
                "fidelity_risk": "material" if material_risk else "unknown",
                "runtime_or_base_change_is_material": material_risk,
                "bounded_rerun_revalidation_required_after_any_later_authorized_rebuild": True,
                "packet_itself_authorizes_rebuild": False,
            },
            authorization=_authorization(),
            request_statuses=list(
                dict.fromkeys(
                    [
                        OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_PACKET_READY.value,
                        OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN.value,
                        OperatorProvenanceRequestPacketStatus.ORIGINAL_RECIPE_PROVENANCE_REQUIRED.value,
                        OperatorProvenanceRequestPacketStatus.PINNED_BASE_IMAGE_DIGEST_REQUIRED.value,
                        OperatorProvenanceRequestPacketStatus.ORIGINAL_BUILD_CONTEXT_REQUIRED.value,
                        OperatorProvenanceRequestPacketStatus.TOOLCHAIN_PROVENANCE_REQUIRED.value,
                        OperatorProvenanceRequestPacketStatus.GO_RUNTIME_ORIGINAL_CONFIRMATION_REQUIRED.value,
                        OperatorProvenanceRequestPacketStatus.GO_REMEDIATION_TARGET_CONFIRMED.value,
                        OperatorProvenanceRequestPacketStatus.MATERIAL_FIDELITY_RISK_DISCLOSED.value,
                        *_blocked_statuses(),
                    ]
                )
            ),
            upstream_records=_upstream_records(decision, chain),
            reasons=[
                "partial_provenance_decision_requires_operator_authority_gap_packet",
                "original_recipe_and_base_digest_required_before_rebuild_authority",
                "go_runtime_remediation_target_recorded_but_not_authorized_for_build",
            ],
            cache_ready=False,
            executable=False,
        )
        path = write_operator_provenance_request_packet_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _load_and_validate_chain(
        self, decision: dict[str, Any]
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        errors: list[str] = []
        paths = {
            "remediation_plan": Path(str(decision.get("remediation_plan") or "")),
            "recipe_recovery": Path(str(decision.get("recipe_recovery") or "")),
            "provenance_gap": Path(str(decision.get("provenance_gap") or "")),
            "recipe_provenance_recovery": Path(
                str(decision.get("recipe_provenance_recovery") or "")
            ),
        }
        records: dict[str, dict[str, Any]] = {}
        validators = {
            "remediation_plan": verify_cleanroom_image_remediation_plan_record,
            "recipe_recovery": verify_cleanroom_build_recipe_recovery_record,
            "provenance_gap": verify_cleanroom_build_recipe_provenance_gap_record,
            "recipe_provenance_recovery": verify_cleanroom_recipe_provenance_recovery_record,
        }
        image = str(decision.get("image_reference") or "")
        digest = str(decision.get("image_digest") or "")
        for name, path in paths.items():
            resolved = self._resolve(path)
            record = _read_json(resolved) if str(path) and resolved.is_file() else {}
            records[name] = record
            if not validators[name](record):
                errors.append(f"{name}_missing_or_invalid")
                continue
            if str(record.get("image_reference") or "") != image:
                errors.append(f"{name}_image_mismatch")
            if str(record.get("image_digest") or "") != digest:
                errors.append(f"{name}_digest_mismatch")
        return records, errors

    def _write_blocked(
        self,
        *,
        status: str,
        decision_path: Path,
        decision: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        image = str(decision.get("image_reference") or self.config.target_image)
        digest = str(decision.get("image_digest") or self.config.target_digest)
        record = make_operator_provenance_request_packet_record(
            status=status,
            image_reference=image,
            image_digest=digest,
            rebuild_quarantine_decision=_rel(self.config.root, decision_path),
            current_decision=str(decision.get("decision") or decision.get("status") or ""),
            required_evidence=[],
            missing_evidence=["valid_rebuild_quarantine_decision_chain"],
            acceptance_criteria=[],
            acceptable_provenance_forms=[],
            unacceptable_provenance_forms=_unacceptable_forms(),
            operator_admission_checklist=[],
            toolchain_requirements={},
            benchmark_fidelity_impact={"packet_itself_authorizes_rebuild": False},
            authorization=_authorization(),
            request_statuses=[status, *_blocked_statuses()],
            upstream_records={},
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_operator_provenance_request_packet_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _required_evidence(*, current_go: str, target_go: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "original_cleanroom_build_recipe",
            "requirement": "Exact original Dockerfile, Containerfile, build script, or reproducible build recipe used for the target cleanroom image.",
            "closes_gap": "ORIGINAL_RECIPE_MISSING",
            "must_include": [
                "content hash",
                "source path or repository reference",
                "operator/source provenance",
                "build arguments if used",
            ],
        },
        {
            "id": "pinned_base_image_digest",
            "requirement": "Exact base image reference pinned by digest with source registry metadata.",
            "closes_gap": "BASE_IMAGE_DIGEST_MISSING",
            "must_include": [
                "registry",
                "repository",
                "tag if any",
                "sha256 digest",
                "manifest lookup/provenance record",
            ],
        },
        {
            "id": "original_build_context",
            "requirement": "Original build context or explicit statement that no external context was used.",
            "closes_gap": "ORIGINAL_BUILD_CONTEXT_UNKNOWN",
            "must_include": [
                "source archive/hash or repository commit",
                "included files list",
                "exclusions if relevant",
            ],
        },
        {
            "id": "toolchain_version_provenance",
            "requirement": "Toolchain source/version provenance for original and remediated Go runtime.",
            "closes_gap": "TOOLCHAIN_PROVENANCE_MISSING",
            "must_include": [
                f"original Go runtime confirmation: {current_go}",
                f"remediation target confirmation: {target_go}",
                "download URL or package source",
                "checksum/digest",
            ],
        },
    ]


def _missing_evidence(*, original_gap_open: bool, base_gap_open: bool) -> list[str]:
    missing: list[str] = []
    if original_gap_open:
        missing.extend(["original_cleanroom_build_recipe", "original_build_context"])
    if base_gap_open:
        missing.append("pinned_base_image_digest")
    missing.extend(["toolchain_version_provenance", "operator_signed_source_base_recipe_binding"])
    return list(dict.fromkeys(missing))


def _acceptance_criteria() -> list[dict[str, Any]]:
    return [
        {
            "id": "exact_target_binding",
            "criteria": "Supplied provenance must bind to programbench/doxygen_1776_doxygen.966d98e:task_cleanroom and sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72.",
        },
        {
            "id": "recipe_and_base_digest_complete",
            "criteria": "Original recipe and pinned base image digest must both be present; either alone remains quarantine-only.",
        },
        {
            "id": "operator_signed",
            "criteria": "Operator packet must tie source, base digest, recipe, toolchain provenance, and target image together.",
        },
        {
            "id": "later_lock_required",
            "criteria": "Acceptance only enables a later operator provenance admission review; it does not rebuild, hydrate, execute, or train.",
        },
    ]


def _acceptable_forms() -> list[str]:
    return [
        "original Dockerfile/build recipe with provenance",
        "pinned base image digest and source registry metadata",
        "signed internal cache/build record",
        "reproducible official build recipe",
        "local image tar plus matching build provenance",
        "operator-signed provenance packet tying source, base digest, recipe, and target image together",
    ]


def _unacceptable_forms() -> list[str]:
    return [
        "latest tags",
        "name-only base images",
        "inferred official images",
        "OCI history alone",
        "reconstructed Dockerfile-style steps alone",
        "broad web search results",
        "unverified public images",
        "fixture admissions",
        "screenshots or prose claims without digest/source linkage",
    ]


def _operator_checklist() -> list[str]:
    return [
        "Confirm target image reference and digest exactly.",
        "Provide original cleanroom Dockerfile/build recipe with source and content hash.",
        "Provide pinned base image digest and registry metadata.",
        "Provide original build context or a signed no-context statement.",
        "Confirm original Go runtime version 1.21.0 and provide its source/checksum.",
        "Confirm remediation target Go runtime 1.24.13 and provide its source/checksum.",
        "State benchmark-fidelity impact of any runtime/base change.",
        "Sign the provenance packet binding recipe, base digest, build context, toolchain, and target image.",
    ]


def _authorization() -> dict[str, bool]:
    return {
        "operator_provenance_requested": True,
        "operator_provenance_admitted": False,
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


def _blocked_statuses() -> list[str]:
    return [
        OperatorProvenanceRequestPacketStatus.REBUILD_NOT_AUTHORIZED.value,
        OperatorProvenanceRequestPacketStatus.DOCKER_PULL_NOT_AUTHORIZED.value,
        OperatorProvenanceRequestPacketStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
        OperatorProvenanceRequestPacketStatus.HYDRATION_NOT_AUTHORIZED.value,
        OperatorProvenanceRequestPacketStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
        OperatorProvenanceRequestPacketStatus.CACHE_READY_FALSE.value,
        OperatorProvenanceRequestPacketStatus.EXECUTABLE_FALSE.value,
        OperatorProvenanceRequestPacketStatus.TRAINING_INELIGIBLE.value,
    ]


def _upstream_records(decision: dict[str, Any], chain: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        "remediation_plan": str(decision.get("remediation_plan") or ""),
        "recipe_recovery": str(decision.get("recipe_recovery") or ""),
        "provenance_gap": str(decision.get("provenance_gap") or ""),
        "recipe_provenance_recovery": str(decision.get("recipe_provenance_recovery") or ""),
        "chain_verified": str(bool(chain)),
    }


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
        description="Write a ProgramBench operator provenance request packet."
    )
    parser.add_argument("rebuild_quarantine_decision", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_operator_provenance_requests"),
    )
    parser.add_argument("--target-image", default="")
    parser.add_argument("--target-digest", default="")
    args = parser.parse_args()
    result = ProgramBenchOperatorProvenanceRequestPacket(
        OperatorProvenanceRequestPacketConfig(
            root=args.root,
            output_dir=args.output_dir,
            target_image=args.target_image,
            target_digest=args.target_digest,
        )
    ).write_packet(args.rebuild_quarantine_decision)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
