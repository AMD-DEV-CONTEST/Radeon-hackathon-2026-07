from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel

FORMAL_MODEL_SOURCE_VERSION = "colorgraph.formal-model-source-registry/v1"

FormalCandidateId = Literal[
    "current_segformer_b0",
    "depth_anything_v2_small",
    "frame_depth_anything_v2_small",
    "sam21",
    "sam31",
    "cutie",
    "sea_raft",
    "segformer_b5",
    "oneformer_ade20k_swin_large",
]
REQUIRED_FORMAL_CANDIDATES: tuple[FormalCandidateId, ...] = (
    "current_segformer_b0",
    "depth_anything_v2_small",
    "frame_depth_anything_v2_small",
    "sam21",
    "sam31",
    "cutie",
    "sea_raft",
    "segformer_b5",
    "oneformer_ade20k_swin_large",
)


class FormalModelSourcePolicy(StrictEvaluationModel):
    maximum_source_age_days: int = Field(default=90, gt=0)
    require_commercial_use: bool = True
    require_redistribution: bool = True


class FormalProjectAuthorizationReference(StrictEvaluationModel):
    authorization_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_use_authorized: bool
    license_acceptance_authorized: bool
    checkpoint_actions_authorized: bool
    public_redistribution_authorized: bool = False
    human_gold_deferred: bool = True


class FormalModelArtifact(StrictEvaluationModel):
    kind: Literal["code", "weights"]
    url: str = Field(pattern=r"^https://")
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    license_id: str | None = None
    license_url: str | None = Field(default=None, pattern=r"^https://")
    commercial_use_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    checked_on: date
    installed: bool = False
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    official_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_installation(self) -> FormalModelArtifact:
        if self.installed != (self.content_sha256 is not None):
            raise ValueError(
                "installed model artifacts must carry a content SHA-256, "
                "and uninstalled artifacts must not"
            )
        if self.commercial_use_allowed is True and (
            not self.license_id or self.license_url is None
        ):
            raise ValueError(
                "commercially allowed artifacts require an explicit license"
            )
        if self.redistribution_allowed is True and (
            self.commercial_use_allowed is not True
        ):
            raise ValueError(
                "redistribution cannot pass while commercial use is unresolved"
            )
        return self


class FormalModelCandidate(StrictEvaluationModel):
    candidate_id: FormalCandidateId
    name: str = Field(min_length=1)
    task_ids: list[str] = Field(min_length=1)
    code: FormalModelArtifact
    weights: FormalModelArtifact
    runtime_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidate(self) -> FormalModelCandidate:
        if self.code.kind != "code" or self.weights.kind != "weights":
            raise ValueError("formal model candidate code/weight kinds are swapped")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("formal model task IDs must be unique")
        if any(not task_id.startswith("CG-") for task_id in self.task_ids):
            raise ValueError("formal model task IDs must use CG identifiers")
        return self


class FormalModelSourceManifest(StrictEvaluationModel):
    schema_version: str = FORMAL_MODEL_SOURCE_VERSION
    checked_on: date
    project_authorization: FormalProjectAuthorizationReference
    policy: FormalModelSourcePolicy = Field(
        default_factory=FormalModelSourcePolicy
    )
    candidates: list[FormalModelCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> FormalModelSourceManifest:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("formal model candidate IDs must be unique")
        return self


class FormalArtifactAudit(StrictEvaluationModel):
    kind: Literal["code", "weights"]
    immutable_source_passed: bool
    source_freshness_passed: bool
    license_explicit: bool
    commercial_use_passed: bool
    redistribution_passed: bool
    installed_and_hashed: bool
    blockers: list[str]


class FormalCandidateAudit(StrictEvaluationModel):
    candidate_id: FormalCandidateId
    code: FormalArtifactAudit
    weights: FormalArtifactAudit
    license_gate_passed: bool
    source_gate_passed: bool
    runtime_ready: bool
    runtime_blockers: list[str]


class FormalModelSourceAuditReport(StrictEvaluationModel):
    schema_version: str = FORMAL_MODEL_SOURCE_VERSION
    evaluator_version: str = FORMAL_MODEL_SOURCE_VERSION
    created_at: datetime
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_integrity_passed: bool
    missing_candidates: list[FormalCandidateId]
    unexpected_candidates: list[str]
    project_authorization: FormalProjectAuthorizationReference
    project_execution_authorized: bool
    audits: list[FormalCandidateAudit]
    license_cleared_candidates: list[FormalCandidateId]
    runtime_ready_candidates: list[FormalCandidateId]
    notes: list[str] = Field(default_factory=list)


def _audit_artifact(
    artifact: FormalModelArtifact,
    *,
    as_of: date,
    policy: FormalModelSourcePolicy,
) -> FormalArtifactAudit:
    age_days = (as_of - artifact.checked_on).days
    immutable_source = artifact.revision is not None
    freshness = 0 <= age_days <= policy.maximum_source_age_days
    license_explicit = (
        bool(artifact.license_id) and artifact.license_url is not None
    )
    commercial = (
        artifact.commercial_use_allowed is True
        if policy.require_commercial_use
        else artifact.commercial_use_allowed is not False
    )
    redistribution = (
        artifact.redistribution_allowed is True
        if policy.require_redistribution
        else artifact.redistribution_allowed is not False
    )
    blockers: list[str] = []
    if not immutable_source:
        blockers.append("immutable_revision_missing")
    if not freshness:
        blockers.append("official_source_stale_or_future_dated")
    if not license_explicit:
        blockers.append("license_not_explicit")
    if not commercial:
        blockers.append("commercial_use_not_cleared")
    if not redistribution:
        blockers.append("redistribution_not_cleared")
    if not artifact.installed:
        blockers.append("artifact_not_installed")
    if artifact.content_sha256 is None:
        blockers.append("content_sha256_missing")
    return FormalArtifactAudit(
        kind=artifact.kind,
        immutable_source_passed=immutable_source,
        source_freshness_passed=freshness,
        license_explicit=license_explicit,
        commercial_use_passed=commercial,
        redistribution_passed=redistribution,
        installed_and_hashed=(
            artifact.installed and artifact.content_sha256 is not None
        ),
        blockers=sorted(set(blockers)),
    )


def audit_formal_model_sources(
    manifest: FormalModelSourceManifest,
    *,
    manifest_path: str,
    manifest_sha256: str,
    created_at: datetime | None = None,
) -> FormalModelSourceAuditReport:
    expected = set(REQUIRED_FORMAL_CANDIDATES)
    actual = {candidate.candidate_id for candidate in manifest.candidates}
    missing_candidates = [
        candidate_id
        for candidate_id in REQUIRED_FORMAL_CANDIDATES
        if candidate_id not in actual
    ]
    unexpected_candidates = sorted(actual - expected)
    registry_integrity = not missing_candidates and not unexpected_candidates
    audits: list[FormalCandidateAudit] = []
    for candidate in manifest.candidates:
        code = _audit_artifact(
            candidate.code,
            as_of=manifest.checked_on,
            policy=manifest.policy,
        )
        weights = _audit_artifact(
            candidate.weights,
            as_of=manifest.checked_on,
            policy=manifest.policy,
        )
        license_gate = all(
            artifact.license_explicit
            and artifact.commercial_use_passed
            and artifact.redistribution_passed
            for artifact in (code, weights)
        )
        source_gate = all(
            artifact.immutable_source_passed
            and artifact.source_freshness_passed
            for artifact in (code, weights)
        )
        runtime_blockers: list[str] = []
        if not license_gate:
            runtime_blockers.append("license_gate_not_passed")
        if not source_gate:
            runtime_blockers.append("source_gate_not_passed")
        if not code.installed_and_hashed:
            runtime_blockers.append("code_not_installed_and_hashed")
        if not weights.installed_and_hashed:
            runtime_blockers.append("weights_not_installed_and_hashed")
        if candidate.runtime_report_sha256 is None:
            runtime_blockers.append("runtime_report_missing")
        audits.append(
            FormalCandidateAudit(
                candidate_id=candidate.candidate_id,
                code=code,
                weights=weights,
                license_gate_passed=license_gate,
                source_gate_passed=source_gate,
                runtime_ready=not runtime_blockers,
                runtime_blockers=sorted(runtime_blockers),
            )
        )
    return FormalModelSourceAuditReport(
        created_at=created_at or datetime.now(UTC),
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        registry_integrity_passed=registry_integrity,
        missing_candidates=missing_candidates,
        unexpected_candidates=unexpected_candidates,
        project_authorization=manifest.project_authorization,
        project_execution_authorized=all(
            (
                manifest.project_authorization.model_use_authorized,
                manifest.project_authorization.license_acceptance_authorized,
                manifest.project_authorization.checkpoint_actions_authorized,
            )
        ),
        audits=audits,
        license_cleared_candidates=[
            audit.candidate_id
            for audit in audits
            if audit.license_gate_passed and audit.source_gate_passed
        ],
        runtime_ready_candidates=[
            audit.candidate_id for audit in audits if audit.runtime_ready
        ],
        notes=[
            (
                "This machine audit records upstream license statements; it is "
                "not legal advice or a substitute for organizational approval."
            ),
            (
                "A repository revision is not a checkpoint content hash. Runtime "
                "readiness requires installed bytes, SHA-256, and a local report."
            ),
            (
                "Project authorization permits local model/checkpoint work but "
                "does not alter upstream terms or authorize extra redistribution."
            ),
            "No model checkpoint was downloaded by this source audit.",
        ],
    )


def audit_formal_model_sources_file(
    manifest_path: str | Path,
    output_path: str | Path,
) -> FormalModelSourceAuditReport:
    source = Path(manifest_path).resolve()
    content = source.read_bytes()
    manifest = FormalModelSourceManifest.model_validate_json(content)
    report = audit_formal_model_sources(
        manifest,
        manifest_path=str(source),
        manifest_sha256=hashlib.sha256(content).hexdigest(),
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
