from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel

RESEARCH_WATCH_VERSION = "colorgraph.research-watch-gate/v1"

ResearchCategory = Literal[
    "shot_detection",
    "video_depth",
    "video_segmentation",
    "creative_agent",
    "color_model",
]
SourceKind = Literal["paper", "code", "release", "license", "weights", "project"]
Availability = Literal["available", "unavailable", "undocumented"]
LicenseDisposition = Literal[
    "commercial_allowed",
    "noncommercial",
    "requires_review",
    "undocumented",
]
ValidationStatus = Literal["passed", "failed", "not_run"]
TargetPlatform = Literal["windows", "rocm"]
PromotionStatus = Literal[
    "watch",
    "eligible_for_formal_todo",
    "promoted",
    "invalid_premature_promotion",
]


class ResearchSource(StrictEvaluationModel):
    kind: SourceKind
    url: str = Field(pattern=r"^https://")
    checked_on: date
    note: str = Field(min_length=1)


class ResearchArtifactEvidence(StrictEvaluationModel):
    availability: Availability
    license_id: str | None = None
    license_disposition: LicenseDisposition = "undocumented"
    immutable_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ResearchRuntimeEvidence(StrictEvaluationModel):
    reproducibility_status: ValidationStatus = "not_run"
    reproducibility_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    peak_vram_mb: float | None = Field(default=None, gt=0)
    tested_platforms: list[TargetPlatform] = Field(default_factory=list)
    passed_platforms: list[TargetPlatform] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_platform_results(self) -> ResearchRuntimeEvidence:
        if len(set(self.tested_platforms)) != len(self.tested_platforms):
            raise ValueError("tested_platforms must not contain duplicates")
        if len(set(self.passed_platforms)) != len(self.passed_platforms):
            raise ValueError("passed_platforms must not contain duplicates")
        if not set(self.passed_platforms).issubset(self.tested_platforms):
            raise ValueError("passed_platforms must be a subset of tested_platforms")
        return self


class ResearchGoldEvidence(StrictEvaluationModel):
    status: ValidationStatus = "not_run"
    report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class ResearchWatchCandidate(StrictEvaluationModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1)
    category: ResearchCategory
    sources: list[ResearchSource] = Field(min_length=1)
    code: ResearchArtifactEvidence
    weights: ResearchArtifactEvidence
    runtime: ResearchRuntimeEvidence
    gold_set: ResearchGoldEvidence
    formal_todo_id: str | None = Field(
        default=None,
        pattern=r"^CG-[A-Z0-9]+(?:-[A-Z0-9]+)*$",
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_coverage(self) -> ResearchWatchCandidate:
        source_kinds = {source.kind for source in self.sources}
        if self.code.availability == "available" and "code" not in source_kinds:
            raise ValueError("available code requires an official code source")
        if self.weights.availability == "available" and "weights" not in source_kinds:
            raise ValueError("available weights require an official weights source")
        if (
            self.code.license_disposition != "undocumented"
            or self.weights.license_disposition != "undocumented"
        ) and "license" not in source_kinds:
            raise ValueError("documented license disposition requires a license source")
        return self


class ResearchWatchPolicy(StrictEvaluationModel):
    target_vram_limit_mb: int = Field(default=16_384, gt=0)
    required_platforms_any_of: list[TargetPlatform] = Field(
        default_factory=lambda: ["windows", "rocm"],
        min_length=1,
    )
    maximum_source_age_days: int = Field(default=90, gt=0)

    @model_validator(mode="after")
    def validate_platform_policy(self) -> ResearchWatchPolicy:
        if len(set(self.required_platforms_any_of)) != len(
            self.required_platforms_any_of
        ):
            raise ValueError("required_platforms_any_of must not contain duplicates")
        return self


class ResearchWatchManifest(StrictEvaluationModel):
    schema_version: str = RESEARCH_WATCH_VERSION
    checked_on: date
    policy: ResearchWatchPolicy = Field(default_factory=ResearchWatchPolicy)
    candidates: list[ResearchWatchCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry(self) -> ResearchWatchManifest:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate_id values must be unique")
        todo_ids = [
            candidate.formal_todo_id
            for candidate in self.candidates
            if candidate.formal_todo_id is not None
        ]
        if len(set(todo_ids)) != len(todo_ids):
            raise ValueError("formal_todo_id values must be unique")
        for candidate in self.candidates:
            for source in candidate.sources:
                if source.checked_on > self.checked_on:
                    raise ValueError(
                        f"{candidate.candidate_id} source check is newer than the manifest"
                    )
        return self


class ResearchCandidateAudit(StrictEvaluationModel):
    candidate_id: str
    name: str
    category: ResearchCategory
    status: PromotionStatus
    promotion_ready: bool
    formal_todo_id: str | None
    blockers: list[str]


class ResearchWatchAuditReport(StrictEvaluationModel):
    schema_version: str = RESEARCH_WATCH_VERSION
    audit_version: str = RESEARCH_WATCH_VERSION
    created_at: datetime
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_on: date
    policy: ResearchWatchPolicy
    candidates: list[ResearchCandidateAudit]
    watch_candidates: list[str]
    eligible_candidates: list[str]
    promoted_candidates: list[str]
    invalid_candidates: list[str]
    registry_integrity_passed: bool
    notes: list[str] = Field(default_factory=list)


def load_research_watch_manifest(
    path: str | Path,
) -> ResearchWatchManifest:
    source = Path(path).resolve()
    return ResearchWatchManifest.model_validate_json(source.read_text(encoding="utf-8"))


def _candidate_blockers(
    candidate: ResearchWatchCandidate,
    *,
    policy: ResearchWatchPolicy,
    checked_on: date,
) -> list[str]:
    blockers: list[str] = []
    source_kinds = {source.kind for source in candidate.sources}
    oldest_allowed_ordinal = checked_on.toordinal() - policy.maximum_source_age_days

    if any(source.checked_on.toordinal() < oldest_allowed_ordinal for source in candidate.sources):
        blockers.append("official_source_check_stale")

    if candidate.code.availability != "available":
        blockers.append("code_unavailable")
    elif "code" not in source_kinds:
        blockers.append("official_code_source_missing")
    if not candidate.code.license_id:
        blockers.append("code_license_missing")
    if candidate.code.license_disposition != "commercial_allowed":
        blockers.append("code_license_not_commercially_cleared")
    if candidate.code.immutable_revision is None:
        blockers.append("source_revision_unfrozen")

    if candidate.weights.availability != "available":
        blockers.append("weights_unavailable")
    elif "weights" not in source_kinds:
        blockers.append("official_weights_source_missing")
    if not candidate.weights.license_id:
        blockers.append("weights_license_missing")
    if candidate.weights.license_disposition != "commercial_allowed":
        blockers.append("weights_license_not_commercially_cleared")
    if candidate.weights.sha256 is None:
        blockers.append("weights_sha256_unfrozen")

    if candidate.runtime.reproducibility_status != "passed":
        blockers.append("reproducibility_not_passed")
    if candidate.runtime.reproducibility_report_sha256 is None:
        blockers.append("reproducibility_report_missing")
    if candidate.runtime.peak_vram_mb is None:
        blockers.append("target_vram_not_measured")
    elif candidate.runtime.peak_vram_mb > policy.target_vram_limit_mb:
        blockers.append("target_vram_limit_exceeded")
    if not set(candidate.runtime.passed_platforms).intersection(
        policy.required_platforms_any_of
    ):
        blockers.append("target_platform_not_passed")

    if candidate.gold_set.status != "passed":
        blockers.append("gold_set_not_passed")
    if candidate.gold_set.report_sha256 is None:
        blockers.append("gold_set_report_missing")
    return sorted(set(blockers))


def audit_research_watch(
    manifest: ResearchWatchManifest,
    *,
    manifest_path: str,
    manifest_sha256: str,
    created_at: datetime | None = None,
) -> ResearchWatchAuditReport:
    candidate_reports: list[ResearchCandidateAudit] = []
    for candidate in manifest.candidates:
        blockers = _candidate_blockers(
            candidate,
            policy=manifest.policy,
            checked_on=manifest.checked_on,
        )
        promotion_ready = not blockers
        if candidate.formal_todo_id is not None and not promotion_ready:
            status: PromotionStatus = "invalid_premature_promotion"
        elif candidate.formal_todo_id is not None:
            status = "promoted"
        elif promotion_ready:
            status = "eligible_for_formal_todo"
        else:
            status = "watch"
        candidate_reports.append(
            ResearchCandidateAudit(
                candidate_id=candidate.candidate_id,
                name=candidate.name,
                category=candidate.category,
                status=status,
                promotion_ready=promotion_ready,
                formal_todo_id=candidate.formal_todo_id,
                blockers=blockers,
            )
        )

    watch_candidates = sorted(
        report.candidate_id for report in candidate_reports if report.status == "watch"
    )
    eligible_candidates = sorted(
        report.candidate_id
        for report in candidate_reports
        if report.status == "eligible_for_formal_todo"
    )
    promoted_candidates = sorted(
        report.candidate_id for report in candidate_reports if report.status == "promoted"
    )
    invalid_candidates = sorted(
        report.candidate_id
        for report in candidate_reports
        if report.status == "invalid_premature_promotion"
    )
    return ResearchWatchAuditReport(
        created_at=created_at or datetime.now(UTC),
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        checked_on=manifest.checked_on,
        policy=manifest.policy,
        candidates=candidate_reports,
        watch_candidates=watch_candidates,
        eligible_candidates=eligible_candidates,
        promoted_candidates=promoted_candidates,
        invalid_candidates=invalid_candidates,
        registry_integrity_passed=not invalid_candidates,
        notes=[
            "Watch status is expected and is not a failed audit.",
            (
                "A candidate becomes eligible only after artifact, commercial-license, "
                "reproducibility, target-memory, Windows/ROCm, and Gold Set gates pass."
            ),
            "Eligibility creates a formal TODO; it does not authorize a production default.",
        ],
    )


def audit_research_watch_file(
    manifest_path: str | Path,
    output_path: str | Path | None = None,
) -> ResearchWatchAuditReport:
    source = Path(manifest_path).resolve()
    content = source.read_bytes()
    manifest = ResearchWatchManifest.model_validate_json(content)
    report = audit_research_watch(
        manifest,
        manifest_path=str(source),
        manifest_sha256=hashlib.sha256(content).hexdigest(),
    )
    if output_path is not None:
        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report
