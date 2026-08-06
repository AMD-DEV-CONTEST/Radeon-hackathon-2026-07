from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel

CREATIVE_PRODUCTION_MANIFEST_VERSION = "colorgraph.creative-production-manifest/v3"
CREATIVE_PRODUCTION_AUDIT_VERSION = (
    "colorgraph.creative-production-evidence-audit/v3"
)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CreativeArtifactReference(StrictEvaluationModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("creative evidence paths must be relative and contained")
        return value


class CreativeGoldArtifactSet(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    media: CreativeArtifactReference
    annotation: CreativeArtifactReference
    license_evidence: CreativeArtifactReference


class CreativeCandidateArtifact(StrictEvaluationModel):
    candidate_id: str = Field(min_length=1)
    output: CreativeArtifactReference
    source_graph: CreativeArtifactReference
    run_request: CreativeArtifactReference
    pipeline_result: CreativeArtifactReference
    execution_evidence: dict[str, CreativeArtifactReference] = Field(
        min_length=1
    )


class CreativeReviewerAttestation(StrictEvaluationModel):
    reviewer_id: str = Field(min_length=1)
    attestation: CreativeArtifactReference
    source_submission: CreativeArtifactReference
    review_response: CreativeArtifactReference
    qualification_approved_by: str = Field(min_length=1)
    years_experience: float = Field(ge=1)
    roles: list[str] = Field(min_length=1)
    color_vision_screened: bool
    calibrated_display_confirmed: bool
    signed_at: datetime

    @model_validator(mode="after")
    def validate_independent_approval(self) -> CreativeReviewerAttestation:
        if self.qualification_approved_by == self.reviewer_id:
            raise ValueError("reviewers cannot approve their own qualification")
        return self


class CreativeReviewerResponseEnvelope(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-reviewer-response/v1"] = (
        "colorgraph.creative-reviewer-response/v1"
    )
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    submitted_at: datetime
    source_submission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviews: list[dict[str, Any]] = Field(min_length=1)


class CreativeProductionManifest(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-production-manifest/v3"] = (
        CREATIVE_PRODUCTION_MANIFEST_VERSION
    )
    manifest_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    authorized_by: list[str] = Field(min_length=1)
    authorized_at: datetime
    items_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewers_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviews_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_records_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenges_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    item_artifacts: list[CreativeGoldArtifactSet] = Field(min_length=1)
    candidate_artifacts: list[CreativeCandidateArtifact] = Field(min_length=1)
    reviewer_attestations: list[CreativeReviewerAttestation] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_unique_bindings(self) -> CreativeProductionManifest:
        for label, values in (
            ("item", [item.item_id for item in self.item_artifacts]),
            (
                "candidate",
                [item.candidate_id for item in self.candidate_artifacts],
            ),
            (
                "reviewer",
                [item.reviewer_id for item in self.reviewer_attestations],
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate creative production {label} binding")
        if len(self.authorized_by) != len(set(self.authorized_by)):
            raise ValueError("creative production authorizers must be unique")
        return self


class CreativeProductionEvidenceAudit(StrictEvaluationModel):
    schema_version: Literal[
        "colorgraph.creative-production-evidence-audit/v3"
    ] = CREATIVE_PRODUCTION_AUDIT_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_id: str
    dataset_version: str
    manifest_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_item_artifacts: int = Field(ge=0)
    checked_candidate_artifacts: int = Field(ge=0)
    checked_candidate_execution_artifacts: int = Field(ge=0)
    checked_reviewer_attestations: int = Field(ge=0)
    checked_reviewer_responses: int = Field(ge=0)
    issues: list[str]
    passed: bool


def creative_bundle_component_digests(bundle: Any) -> dict[str, str]:
    return {
        "items_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in bundle.items]
        ),
        "candidates_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in bundle.candidates]
        ),
        "reviewers_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in bundle.reviewers]
        ),
        "reviews_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in bundle.reviews]
        ),
        "judge_records_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in bundle.judge_records]
        ),
        "challenges_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in bundle.challenges]
        ),
        "config_sha256": canonical_sha256(bundle.config.model_dump(mode="json")),
    }


def _resolve_artifact(root: Path, reference: CreativeArtifactReference) -> Path:
    path = (root / reference.relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(
            f"creative evidence path escapes its manifest root: "
            f"{reference.relative_path!r}"
        )
    return path


def _check_artifact(
    root: Path,
    reference: CreativeArtifactReference,
    *,
    label: str,
    issues: list[str],
) -> bool:
    try:
        path = _resolve_artifact(root, reference)
    except ValueError as exc:
        issues.append(str(exc))
        return False
    if not path.is_file():
        issues.append(f"{label} is missing: {reference.relative_path}")
        return False
    actual = sha256_file(path)
    if actual != reference.sha256:
        issues.append(
            f"{label} digest mismatch: expected {reference.sha256}, got {actual}"
        )
        return False
    return True


def verify_creative_production_manifest(
    bundle: Any,
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> CreativeProductionEvidenceAudit:
    manifest_path = manifest_path.resolve()
    issues: list[str] = []
    if not manifest_path.is_file():
        return CreativeProductionEvidenceAudit(
            evaluation_id=bundle.evaluation_id,
            dataset_version=bundle.dataset_version,
            manifest_id="missing",
            manifest_sha256=expected_manifest_sha256,
            checked_item_artifacts=0,
            checked_candidate_artifacts=0,
            checked_candidate_execution_artifacts=0,
            checked_reviewer_attestations=0,
            checked_reviewer_responses=0,
            issues=[f"production manifest is missing: {manifest_path}"],
            passed=False,
        )
    actual_manifest_sha256 = sha256_file(manifest_path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        issues.append(
            "production manifest digest mismatch: "
            f"expected {expected_manifest_sha256}, got {actual_manifest_sha256}"
        )
    try:
        manifest = CreativeProductionManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return CreativeProductionEvidenceAudit(
            evaluation_id=bundle.evaluation_id,
            dataset_version=bundle.dataset_version,
            manifest_id="invalid",
            manifest_sha256=actual_manifest_sha256,
            checked_item_artifacts=0,
            checked_candidate_artifacts=0,
            checked_candidate_execution_artifacts=0,
            checked_reviewer_attestations=0,
            checked_reviewer_responses=0,
            issues=[*issues, f"production manifest is invalid: {exc}"],
            passed=False,
        )

    if manifest.evaluation_id != bundle.evaluation_id:
        issues.append("production manifest evaluation_id does not match the bundle")
    if manifest.dataset_version != bundle.dataset_version:
        issues.append("production manifest dataset_version does not match the bundle")
    for field, digest in creative_bundle_component_digests(bundle).items():
        if getattr(manifest, field) != digest:
            issues.append(f"production manifest {field} does not match the bundle")

    root = manifest_path.parent.resolve()
    items = {item.item_id: item for item in bundle.items}
    candidates = {item.candidate_id: item for item in bundle.candidates}
    reviewers = {item.reviewer_id: item for item in bundle.reviewers}
    item_bindings = {item.item_id: item for item in manifest.item_artifacts}
    candidate_bindings = {
        item.candidate_id: item for item in manifest.candidate_artifacts
    }
    reviewer_bindings = {
        item.reviewer_id: item for item in manifest.reviewer_attestations
    }
    if set(item_bindings) != set(items):
        issues.append("production manifest item bindings are incomplete or unexpected")
    if set(candidate_bindings) != set(candidates):
        issues.append(
            "production manifest candidate bindings are incomplete or unexpected"
        )
    if set(reviewer_bindings) != set(reviewers):
        issues.append(
            "production manifest reviewer attestations are incomplete or unexpected"
        )

    checked_items = 0
    for item_id, binding in item_bindings.items():
        item = items.get(item_id)
        if item is None:
            continue
        checked_items += 1
        if binding.media.sha256 != item.media_sha256:
            issues.append(f"{item_id} media digest is not bound to the gold item")
        if binding.annotation.sha256 != item.annotation_sha256:
            issues.append(f"{item_id} annotation digest is not bound to the gold item")
        _check_artifact(
            root,
            binding.media,
            label=f"{item_id} media",
            issues=issues,
        )
        _check_artifact(
            root,
            binding.annotation,
            label=f"{item_id} annotation",
            issues=issues,
        )
        _check_artifact(
            root,
            binding.license_evidence,
            label=f"{item_id} license evidence",
            issues=issues,
        )

    checked_candidates = 0
    checked_candidate_execution_artifacts = 0
    for candidate_id, binding in candidate_bindings.items():
        candidate = candidates.get(candidate_id)
        if candidate is None:
            continue
        checked_candidates += 1
        if binding.output.sha256 != candidate.output_sha256:
            issues.append(
                f"{candidate_id} output digest is not bound to the candidate"
            )
        _check_artifact(
            root,
            binding.output,
            label=f"{candidate_id} output",
            issues=issues,
        )
        execution = candidate.execution
        if (
            binding.source_graph.sha256
            != execution.source_graph_artifact_sha256
        ):
            issues.append(
                f"{candidate_id} source graph is not bound to its execution"
            )
        checked_candidate_execution_artifacts += 1
        _check_artifact(
            root,
            binding.source_graph,
            label=f"{candidate_id} source graph",
            issues=issues,
        )
        if binding.run_request.sha256 != execution.run_request_sha256:
            issues.append(
                f"{candidate_id} run request is not bound to its execution"
            )
        checked_candidate_execution_artifacts += 1
        _check_artifact(
            root,
            binding.run_request,
            label=f"{candidate_id} run request",
            issues=issues,
        )
        if binding.pipeline_result.sha256 != execution.pipeline_result_sha256:
            issues.append(
                f"{candidate_id} pipeline result is not bound to its execution"
            )
        checked_candidate_execution_artifacts += 1
        _check_artifact(
            root,
            binding.pipeline_result,
            label=f"{candidate_id} pipeline result",
            issues=issues,
        )
        expected_evidence = {
            stage.value: digest
            for stage, digest in execution.stage_evidence_sha256.items()
        }
        observed_evidence = {
            stage: reference.sha256
            for stage, reference in binding.execution_evidence.items()
        }
        if observed_evidence != expected_evidence:
            issues.append(
                f"{candidate_id} execution evidence does not match its "
                "frozen ablation manifest"
            )
        for stage, reference in binding.execution_evidence.items():
            checked_candidate_execution_artifacts += 1
            _check_artifact(
                root,
                reference,
                label=f"{candidate_id} {stage} execution evidence",
                issues=issues,
            )

    checked_reviewers = 0
    checked_reviewer_responses = 0
    for reviewer_id, binding in reviewer_bindings.items():
        reviewer = reviewers.get(reviewer_id)
        if reviewer is None:
            continue
        checked_reviewers += 1
        if binding.years_experience != reviewer.years_experience:
            issues.append(f"{reviewer_id} experience does not match its attestation")
        if binding.roles != reviewer.roles:
            issues.append(f"{reviewer_id} roles do not match its attestation")
        if (
            binding.color_vision_screened != reviewer.color_vision_screened
            or binding.calibrated_display_confirmed
            != reviewer.calibrated_display_confirmed
        ):
            issues.append(
                f"{reviewer_id} screening/display claims do not match its attestation"
            )
        _check_artifact(
            root,
            binding.attestation,
            label=f"{reviewer_id} qualification attestation",
            issues=issues,
        )
        if _check_artifact(
            root,
            binding.review_response,
            label=f"{reviewer_id} review response",
            issues=issues,
        ):
            response_path = _resolve_artifact(root, binding.review_response)
            try:
                response = CreativeReviewerResponseEnvelope.model_validate_json(
                    response_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                issues.append(
                    f"{reviewer_id} review response is invalid: {exc}"
                )
            else:
                checked_reviewer_responses += 1
                if response.evaluation_id != bundle.evaluation_id:
                    issues.append(
                        f"{reviewer_id} response evaluation_id does not match"
                    )
                if response.dataset_version != bundle.dataset_version:
                    issues.append(
                        f"{reviewer_id} response dataset_version does not match"
                    )
                if response.reviewer_id != reviewer_id:
                    issues.append(
                        f"{reviewer_id} response identity does not match"
                    )
                if (
                    response.source_submission_sha256
                    != binding.source_submission.sha256
                ):
                    issues.append(
                        f"{reviewer_id} response submission digest does not match"
                    )
                expected_reviews = sorted(
                    (
                        review.model_dump(mode="json")
                        for review in bundle.reviews
                        if review.reviewer_id == reviewer_id
                    ),
                    key=lambda review: review["pair_id"],
                )
                submitted_reviews = sorted(
                    response.reviews,
                    key=lambda review: str(review.get("pair_id", "")),
                )
                if canonical_sha256(submitted_reviews) != canonical_sha256(
                    expected_reviews
                ):
                    issues.append(
                        f"{reviewer_id} response reviews do not match the bundle"
                    )
        _check_artifact(
            root,
            binding.source_submission,
            label=f"{reviewer_id} source submission",
            issues=issues,
        )

    return CreativeProductionEvidenceAudit(
        evaluation_id=bundle.evaluation_id,
        dataset_version=bundle.dataset_version,
        manifest_id=manifest.manifest_id,
        manifest_sha256=actual_manifest_sha256,
        checked_item_artifacts=checked_items,
        checked_candidate_artifacts=checked_candidates,
        checked_candidate_execution_artifacts=(
            checked_candidate_execution_artifacts
        ),
        checked_reviewer_attestations=checked_reviewers,
        checked_reviewer_responses=checked_reviewer_responses,
        issues=issues,
        passed=not issues,
    )
