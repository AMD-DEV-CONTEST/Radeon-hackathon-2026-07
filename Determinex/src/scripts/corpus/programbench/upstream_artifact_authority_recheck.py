#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.alternate_cleanroom_image_provenance_record import (
    verify_alternate_cleanroom_image_provenance_record,
)
from corpus.programbench.cleanroom_image_hydration_record import (
    verify_cleanroom_image_hydration_record,
)
from corpus.programbench.cleanroom_image_scan_record import verify_cleanroom_image_scan_record
from corpus.programbench.cleanroom_image_scan_triage_record import (
    verify_cleanroom_image_scan_triage_record,
)
from corpus.programbench.dockerhub_manifest_provenance_record import (
    verify_dockerhub_manifest_provenance_record,
)
from corpus.programbench.operator_provenance_request_packet_record import (
    verify_operator_provenance_request_packet_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (
    verify_rebuild_provenance_quarantine_decision_record,
)
from corpus.programbench.upstream_artifact_authority_recheck_record import (
    make_upstream_artifact_authority_recheck_record,
    write_upstream_artifact_authority_recheck_record,
)

INSTANCE_ID = "doxygen__doxygen.966d98e"
EXPECTED_DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


class AuthorityValue(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    INCONCLUSIVE = "INCONCLUSIVE"


class ExecutionSecurityPolicy(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED_SCAN_FAILED = "BLOCKED_SCAN_FAILED"
    BLOCKED_POLICY_REVIEW_REQUIRED = "BLOCKED_POLICY_REVIEW_REQUIRED"
    INCONCLUSIVE = "INCONCLUSIVE"


class UpstreamArtifactAuthorityRecheckStatus(str, Enum):
    UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_COMPLETED = "UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_COMPLETED"
    UPSTREAM_ARTIFACT_AUTHORITY_PRESENT = "UPSTREAM_ARTIFACT_AUTHORITY_PRESENT"
    UPSTREAM_ARTIFACT_AUTHORITY_ABSENT = "UPSTREAM_ARTIFACT_AUTHORITY_ABSENT"
    UPSTREAM_ARTIFACT_AUTHORITY_INCONCLUSIVE = "UPSTREAM_ARTIFACT_AUTHORITY_INCONCLUSIVE"
    REBUILD_PROVENANCE_AUTHORITY_ABSENT = "REBUILD_PROVENANCE_AUTHORITY_ABSENT"
    REMEDIATION_AUTHORITY_ABSENT = "REMEDIATION_AUTHORITY_ABSENT"
    OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED = "OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED"
    OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED = (
        "OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED"
    )
    OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_REVIEW = (
        "OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_REVIEW"
    )
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    EXECUTABLE_FALSE = "EXECUTABLE_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class UpstreamArtifactAuthorityRecheckConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_upstream_artifact_authority_recheck")
    instance_id: str = INSTANCE_ID
    expected_digest: str = EXPECTED_DIGEST
    local_authority_paths: list[Path] = field(default_factory=list)


class ProgramBenchUpstreamArtifactAuthorityRecheck:
    def __init__(self, config: UpstreamArtifactAuthorityRecheckConfig | None = None) -> None:
        self.config = config or UpstreamArtifactAuthorityRecheckConfig()

    def recheck(
        self,
        *,
        manifest_record_path: Path,
        operator_request_path: Path,
        rebuild_decision_path: Path,
        scan_record_path: Path,
        hydration_record_path: Path,
        alternate_record_path: Path,
        provider_registry_lock_path: Path | None = None,
        triage_record_path: Path | None = None,
    ) -> dict[str, Any]:
        expected_image = image_name(self.config.instance_id)
        paths = {
            "manifest_record": manifest_record_path,
            "operator_provenance_request": operator_request_path,
            "rebuild_quarantine_decision": rebuild_decision_path,
            "scan_record": scan_record_path,
            "hydration_record": hydration_record_path,
            "alternate_provenance_record": alternate_record_path,
        }
        if provider_registry_lock_path is not None:
            paths["provider_registry_lock"] = provider_registry_lock_path
        if triage_record_path is not None:
            paths["scan_triage_record"] = triage_record_path

        loaded = {name: self._load_record(path) for name, path in paths.items()}
        validation = {name: item["valid"] for name, item in loaded.items()}
        records = {name: item["record"] for name, item in loaded.items()}
        consumed_records = {
            name: _rel(self.config.root, self._resolve(path)) for name, path in paths.items()
        }

        manifest = records["manifest_record"]
        request = records["operator_provenance_request"]
        decision_record = records["rebuild_quarantine_decision"]
        scan = records["scan_record"]
        hydration = records["hydration_record"]
        provider_lock = records.get("provider_registry_lock", {})
        local_usage = self._local_authority_evidence(expected_image)

        image_reference = _first_text(
            manifest.get("image_reference"),
            request.get("image_reference"),
            decision_record.get("image_reference"),
            expected_image,
        )
        image_digest = _first_text(
            manifest.get("manifest_digest"),
            request.get("image_digest"),
            decision_record.get("image_digest"),
            self.config.expected_digest,
        )

        image_consistency = _all_equal(
            expected_image,
            manifest.get("image_reference"),
            request.get("image_reference"),
            decision_record.get("image_reference"),
            scan.get("image_reference"),
            hydration.get("image_reference"),
        )
        digest_consistency = _all_equal(
            self.config.expected_digest,
            manifest.get("manifest_digest"),
            request.get("image_digest"),
            decision_record.get("image_digest"),
            scan.get("expected_digest"),
            scan.get("observed_digest"),
            hydration.get("expected_digest"),
            hydration.get("observed_digest"),
        )
        exact_provider = (
            validation.get("manifest_record") is True
            and manifest.get("status") == "EXACT_REMOTE_MANIFEST_FOUND"
            and manifest.get("registry") == "docker.io"
            and manifest.get("repository") == expected_image.split(":", 1)[0]
            and manifest.get("tag") == "task_cleanroom"
            and manifest.get("manifest_digest") == self.config.expected_digest
            and manifest.get("pulled_layers") is False
            and manifest.get("executed") is False
        )
        provider_registry_allows_exact = validation.get("provider_registry_lock") is True
        upstream_authority_present = (
            expected_image == "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
            and image_consistency
            and digest_consistency
            and exact_provider
            and local_usage["task_cleanroom_distribution_model_present"]
            and local_usage["doxygen_mapping_verified"]
            and (provider_registry_allows_exact or provider_registry_lock_path is None)
        )

        upstream_authority = (
            AuthorityValue.PRESENT.value
            if upstream_authority_present
            else AuthorityValue.INCONCLUSIVE.value
            if exact_provider or local_usage["task_cleanroom_distribution_model_present"]
            else AuthorityValue.ABSENT.value
        )
        rebuild_authority = _rebuild_authority(
            decision_record, validation.get("rebuild_quarantine_decision", False)
        )
        remediation_authority = _remediation_authority(
            decision_record, validation.get("rebuild_quarantine_decision", False)
        )
        execution_policy = _execution_policy(scan, hydration, validation)
        decision = _decision(upstream_authority, execution_policy)
        reasons = _reasons(
            upstream_authority=upstream_authority,
            rebuild_authority=rebuild_authority,
            remediation_authority=remediation_authority,
            execution_policy=execution_policy,
            image_consistency=image_consistency,
            digest_consistency=digest_consistency,
            exact_provider=exact_provider,
        )
        statuses = [
            UpstreamArtifactAuthorityRecheckStatus.UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_COMPLETED.value,
            _authority_status(upstream_authority),
            UpstreamArtifactAuthorityRecheckStatus.REBUILD_PROVENANCE_AUTHORITY_ABSENT.value
            if rebuild_authority == AuthorityValue.ABSENT.value
            else f"REBUILD_PROVENANCE_AUTHORITY_{rebuild_authority}",
            UpstreamArtifactAuthorityRecheckStatus.REMEDIATION_AUTHORITY_ABSENT.value
            if remediation_authority == AuthorityValue.ABSENT.value
            else f"REMEDIATION_AUTHORITY_{remediation_authority}",
            _execution_status(execution_policy),
            UpstreamArtifactAuthorityRecheckStatus.CACHE_READY_FALSE.value,
            UpstreamArtifactAuthorityRecheckStatus.EXECUTABLE_FALSE.value,
            UpstreamArtifactAuthorityRecheckStatus.TRAINING_INELIGIBLE.value,
        ]
        if upstream_authority == AuthorityValue.PRESENT.value:
            statuses.append(
                UpstreamArtifactAuthorityRecheckStatus.OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED.value
            )

        record = make_upstream_artifact_authority_recheck_record(
            status=UpstreamArtifactAuthorityRecheckStatus.UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_COMPLETED.value,
            decision=decision,
            instance_id=self.config.instance_id,
            image_reference=image_reference,
            image_digest=image_digest,
            expected_image_reference=expected_image,
            expected_image_digest=self.config.expected_digest,
            upstream_benchmark_artifact_authority=upstream_authority,
            rebuild_provenance_authority=rebuild_authority,
            remediation_authority=remediation_authority,
            execution_security_policy=execution_policy,
            authority_findings={
                "authority_statuses": list(dict.fromkeys(statuses)),
                "programbench_task_cleanroom_distribution_model": local_usage,
                "exact_provider_manifest": {
                    "present": exact_provider,
                    "registry": manifest.get("registry"),
                    "repository": manifest.get("repository"),
                    "tag": manifest.get("tag"),
                    "manifest_digest": manifest.get("manifest_digest"),
                    "metadata_only_lookup": manifest.get("lookup_method")
                    == "manifest/digest metadata only",
                    "pulled_layers": manifest.get("pulled_layers"),
                    "executed": manifest.get("executed"),
                },
                "provider_registry_exact_path_allowed": provider_registry_allows_exact,
                "authority_boundaries": {
                    "upstream_benchmark_artifact_authority_is_not_rebuild_authority": True,
                    "upstream_benchmark_artifact_authority_is_not_remediation_authority": True,
                    "upstream_benchmark_artifact_authority_is_not_execution_authority": True,
                    "upstream_benchmark_artifact_authority_is_not_training_eligibility": True,
                },
            },
            consumed_records=consumed_records,
            verification={
                "record_signatures_valid": validation,
                "image_mapping_expected": expected_image,
                "image_consistency": image_consistency,
                "digest_consistency": digest_consistency,
                "manifest_digest_matches_expected": manifest.get("manifest_digest")
                == self.config.expected_digest,
                "scan_status": scan.get("status"),
                "hydration_policy_result": hydration.get("policy_result"),
                "alternate_provenance_status": records["alternate_provenance_record"].get("status"),
            },
            authorization=_authorization(),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_upstream_artifact_authority_recheck_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _load_record(self, path: Path) -> dict[str, Any]:
        resolved = self._resolve(path)
        record = _read_json(resolved) if resolved.is_file() else {}
        validator = _validator_for(resolved)
        return {
            "path": _rel(self.config.root, resolved),
            "record": record,
            "valid": bool(record) and validator(record),
        }

    def _local_authority_evidence(self, expected_image: str) -> dict[str, Any]:
        paths = self.config.local_authority_paths or [
            Path("docs/PROGRAMBENCH_FACTORY_ARCHITECTURE.md"),
            Path("docs/PROGRAMBENCH.md"),
            Path("scripts/determinex_programbench_probe.py"),
            Path("scripts/determinex_programbench_agent.py"),
            Path("scripts/programbench_eval_runner.py"),
            Path("scripts/programbench_image_preflight.py"),
        ]
        evidence: list[dict[str, Any]] = []
        mapping_hits = 0
        distribution_hits = 0
        for path in paths:
            resolved = self._resolve(path)
            text = _read_text(resolved)
            if not text:
                evidence.append(
                    {
                        "path": _rel(self.config.root, resolved),
                        "exists": resolved.exists(),
                        "matches": [],
                    }
                )
                continue
            matches: list[str] = []
            if "task_cleanroom" in text and "programbench/" in text:
                distribution_hits += 1
                matches.append("task_cleanroom_programbench_image_reference")
            if (
                "replace('__', '_1776_')" in text
                or "<owner>_1776_<repo>.<hash>:task_cleanroom" in text
            ):
                mapping_hits += 1
                matches.append("instance_id_to_task_cleanroom_mapping")
            if expected_image in text:
                matches.append("exact_doxygen_image_reference")
            evidence.append(
                {
                    "path": _rel(self.config.root, resolved),
                    "exists": resolved.exists(),
                    "matches": matches,
                }
            )
        return {
            "task_cleanroom_distribution_model_present": distribution_hits > 0,
            "doxygen_mapping_verified": image_name(self.config.instance_id) == expected_image
            and mapping_hits > 0,
            "distribution_evidence_count": distribution_hits,
            "mapping_evidence_count": mapping_hits,
            "evidence": evidence,
        }

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def image_name(instance_id: str) -> str:
    return f"programbench/{instance_id.replace('__', '_1776_')}:task_cleanroom"


def _validator_for(path: Path) -> Callable[[dict[str, Any]], bool]:
    text = path.as_posix()
    if "programbench_dockerhub_manifest_provenance" in text:
        return verify_dockerhub_manifest_provenance_record
    if "programbench_operator_provenance_requests" in text:
        return verify_operator_provenance_request_packet_record
    if "programbench_rebuild_provenance_quarantine_decisions" in text:
        return verify_rebuild_provenance_quarantine_decision_record
    if "programbench_cleanroom_image_scans" in text:
        return verify_cleanroom_image_scan_record
    if "programbench_cleanroom_image_hydration" in text:
        return verify_cleanroom_image_hydration_record
    if "programbench_cleanroom_image_scan_triage" in text:
        return verify_cleanroom_image_scan_triage_record
    if "programbench_alternate_cleanroom_image_provenance" in text:
        return verify_alternate_cleanroom_image_provenance_record
    if path.name == "PROGRAMBENCH_ONLINE_PROVIDER_REGISTRY_LOCK_001.json":
        return _provider_registry_lock_valid
    return lambda record: bool(record)


def _provider_registry_lock_valid(record: dict[str, Any]) -> bool:
    blocked = [str(item) for item in record.get("blocked", [])]
    blocked_behavior = [str(item).lower() for item in record.get("blocked_behavior", [])]
    return (
        record.get("lock_id") == "PROGRAMBENCH_ONLINE_PROVIDER_REGISTRY_LOCK_001"
        and "docker_hub_official" in record.get("providers", [])
        and ("broad_search" in blocked or any("broad search" in item for item in blocked_behavior))
        and ("latest_execution" in blocked or any("latest" in item for item in blocked_behavior))
    )


def _rebuild_authority(record: dict[str, Any], valid: bool) -> str:
    if not valid:
        return AuthorityValue.INCONCLUSIVE.value
    findings = record.get("findings") if isinstance(record.get("findings"), dict) else {}
    if (
        record.get("rebuild_provenance_authorized") is True
        or record.get("image_rebuild_authorized") is True
    ):
        return AuthorityValue.PRESENT.value
    if (
        findings.get("rebuild_provenance_authorized") is True
        or findings.get("partial_provenance_is_sufficient_for_rebuild") is True
    ):
        return AuthorityValue.PRESENT.value
    if (
        record.get("rebuild_provenance_authorized") is False
        or record.get("image_rebuild_authorized") is False
    ):
        return AuthorityValue.ABSENT.value
    if (
        findings.get("rebuild_provenance_authorized") is False
        or findings.get("partial_provenance_is_sufficient_for_rebuild") is False
    ):
        return AuthorityValue.ABSENT.value
    auth = record.get("authorization") if isinstance(record.get("authorization"), dict) else {}
    if (
        auth.get("rebuild_authorized") is True
        or auth.get("image_rebuild_authorized") is True
        or auth.get("rebuild_provenance_ready") is True
    ):
        return AuthorityValue.PRESENT.value
    if (
        auth.get("rebuild_authorized") is False
        or auth.get("image_rebuild_authorized") is False
        or auth.get("rebuild_provenance_ready") is False
    ):
        return AuthorityValue.ABSENT.value
    return AuthorityValue.INCONCLUSIVE.value


def _remediation_authority(record: dict[str, Any], valid: bool) -> str:
    if not valid:
        return AuthorityValue.INCONCLUSIVE.value
    auth = record.get("authorization") if isinstance(record.get("authorization"), dict) else {}
    if record.get("image_rebuild_authorized") is True:
        return AuthorityValue.PRESENT.value
    if auth.get("image_rebuild_authorized") is True:
        return AuthorityValue.PRESENT.value
    if record.get("image_rebuild_authorized") is False:
        return AuthorityValue.ABSENT.value
    if auth.get("image_rebuild_authorized") is False:
        return AuthorityValue.ABSENT.value
    if record.get("rebuild_provenance_authorized") is False:
        return AuthorityValue.ABSENT.value
    return AuthorityValue.INCONCLUSIVE.value


def _execution_policy(
    scan: dict[str, Any], hydration: dict[str, Any], validation: dict[str, bool]
) -> str:
    if validation.get("scan_record") and scan.get("status") == "CLEANROOM_IMAGE_SCAN_FAILED":
        return ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value
    if (
        validation.get("hydration_record")
        and hydration.get("policy_result") == "CLEANROOM_IMAGE_POLICY_BLOCKED"
    ):
        return ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value
    if validation.get("scan_record") or validation.get("hydration_record"):
        return ExecutionSecurityPolicy.BLOCKED_POLICY_REVIEW_REQUIRED.value
    return ExecutionSecurityPolicy.INCONCLUSIVE.value


def _decision(upstream_authority: str, execution_policy: str) -> str:
    if upstream_authority != AuthorityValue.PRESENT.value:
        return f"UPSTREAM_ARTIFACT_AUTHORITY_{upstream_authority}"
    if execution_policy == ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value:
        return "OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED_EXECUTION_BLOCKED_SCAN_FAILED"
    if execution_policy == ExecutionSecurityPolicy.BLOCKED_POLICY_REVIEW_REQUIRED.value:
        return "OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED_POLICY_REVIEW_REQUIRED"
    if execution_policy == ExecutionSecurityPolicy.ALLOWED.value:
        return "OFFICIAL_ARTIFACT_EXECUTION_ALLOWED_BY_SECURITY_POLICY"
    return "OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED_EXECUTION_INCONCLUSIVE"


def _authority_status(upstream_authority: str) -> str:
    if upstream_authority == AuthorityValue.PRESENT.value:
        return UpstreamArtifactAuthorityRecheckStatus.UPSTREAM_ARTIFACT_AUTHORITY_PRESENT.value
    if upstream_authority == AuthorityValue.ABSENT.value:
        return UpstreamArtifactAuthorityRecheckStatus.UPSTREAM_ARTIFACT_AUTHORITY_ABSENT.value
    return UpstreamArtifactAuthorityRecheckStatus.UPSTREAM_ARTIFACT_AUTHORITY_INCONCLUSIVE.value


def _execution_status(execution_policy: str) -> str:
    if execution_policy == ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value:
        return UpstreamArtifactAuthorityRecheckStatus.OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED.value
    if execution_policy == ExecutionSecurityPolicy.BLOCKED_POLICY_REVIEW_REQUIRED.value:
        return UpstreamArtifactAuthorityRecheckStatus.OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_REVIEW.value
    return f"EXECUTION_SECURITY_POLICY_{execution_policy}"


def _reasons(
    *,
    upstream_authority: str,
    rebuild_authority: str,
    remediation_authority: str,
    execution_policy: str,
    image_consistency: bool,
    digest_consistency: bool,
    exact_provider: bool,
) -> list[str]:
    reasons: list[str] = []
    if upstream_authority == AuthorityValue.PRESENT.value:
        reasons.append(
            "programbench_task_cleanroom_distribution_model_and_exact_manifest_digest_verified"
        )
    else:
        if not image_consistency:
            reasons.append("image_reference_consistency_not_verified")
        if not digest_consistency:
            reasons.append("digest_consistency_not_verified")
        if not exact_provider:
            reasons.append("exact_provider_manifest_not_verified")
    if rebuild_authority == AuthorityValue.ABSENT.value:
        reasons.append("rebuild_provenance_authority_absent")
    if remediation_authority == AuthorityValue.ABSENT.value:
        reasons.append("remediation_authority_absent")
    if execution_policy == ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value:
        reasons.append("execution_security_policy_blocked_by_failed_scan")
    elif execution_policy == ExecutionSecurityPolicy.BLOCKED_POLICY_REVIEW_REQUIRED.value:
        reasons.append("execution_security_policy_requires_review")
    reasons.extend(["cache_ready_false", "executable_false", "training_eligible_false"])
    return reasons


def _authorization() -> dict[str, bool]:
    return {
        "metadata_only_admitted": True,
        "rebuild_authorized": False,
        "remediation_authorized": False,
        "docker_pull_authorized": False,
        "docker_execution_authorized": False,
        "hydration_authorized": False,
        "programbench_rerun_authorized": False,
        "policy_exception_authorized": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _all_equal(expected: str, *values: object) -> bool:
    return all(str(value or "") == expected for value in values)


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "")
        if text:
            return text
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recheck ProgramBench upstream artifact authority for a task_cleanroom image."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_upstream_artifact_authority_recheck"),
    )
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--expected-digest", default=EXPECTED_DIGEST)
    parser.add_argument("--manifest-record", type=Path, required=True)
    parser.add_argument("--operator-request", type=Path, required=True)
    parser.add_argument("--rebuild-decision", type=Path, required=True)
    parser.add_argument("--scan-record", type=Path, required=True)
    parser.add_argument("--hydration-record", type=Path, required=True)
    parser.add_argument("--alternate-record", type=Path, required=True)
    parser.add_argument("--provider-registry-lock", type=Path, default=None)
    parser.add_argument("--triage-record", type=Path, default=None)
    args = parser.parse_args()
    result = ProgramBenchUpstreamArtifactAuthorityRecheck(
        UpstreamArtifactAuthorityRecheckConfig(
            root=args.root,
            output_dir=args.output_dir,
            instance_id=args.instance_id,
            expected_digest=args.expected_digest,
        )
    ).recheck(
        manifest_record_path=args.manifest_record,
        operator_request_path=args.operator_request,
        rebuild_decision_path=args.rebuild_decision,
        scan_record_path=args.scan_record,
        hydration_record_path=args.hydration_record,
        alternate_record_path=args.alternate_record,
        provider_registry_lock_path=args.provider_registry_lock,
        triage_record_path=args.triage_record,
    )
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
