from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.evaluation.creative_agent import (
    CreativeAgentEvaluationBundle,
    CreativeAgentEvaluationConfig,
    CreativeCandidateObservation,
    CreativeChallengeResult,
    CreativeDimensionScores,
    CreativeEvidenceClass,
    CreativeGoldItem,
    CreativeJudgeRecord,
    CreativeMediaOrigin,
    CreativePairChoice,
    CreativePairReview,
    CreativeReviewer,
    build_creative_agent_review_pairs,
)
from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    CreativeCandidateArtifact,
    CreativeGoldArtifactSet,
    CreativeProductionManifest,
    CreativeReviewerAttestation,
    CreativeReviewerResponseEnvelope,
    canonical_sha256,
    creative_bundle_component_digests,
    sha256_file,
)
from colorgraph.evaluation.models import StrictEvaluationModel

CREATIVE_REVIEW_DRAFT_VERSION = "colorgraph.creative-review-draft/v3"
CREATIVE_REVIEW_PANEL_VERSION = "colorgraph.creative-review-panel/v1"
CREATIVE_REVIEW_FREEZE_VERSION = "colorgraph.creative-review-freeze/v3"
CREATIVE_REVIEW_ASSIGNMENT_VERSION = "colorgraph.creative-review-assignment/v1"
CREATIVE_REVIEW_SUBMISSION_VERSION = "colorgraph.creative-review-submission/v1"


def _digest_component(value: str) -> str:
    """Return a short deterministic path component for Windows-safe freezes."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _write_model(path: Path, model: StrictEvaluationModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def _resolve_reference(
    root: Path,
    reference: CreativeArtifactReference,
) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / reference.relative_path).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError(
            f"creative review artifact escapes its root: "
            f"{reference.relative_path!r}"
        )
    return path


def _verify_reference(
    root: Path,
    reference: CreativeArtifactReference,
    *,
    label: str,
) -> Path:
    path = _resolve_reference(root, reference)
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != reference.sha256:
        raise ValueError(
            f"{label} digest mismatch: expected {reference.sha256}, got {actual}"
        )
    return path


def _copy_reference(
    *,
    source_root: Path,
    reference: CreativeArtifactReference,
    destination_root: Path,
    category: str,
    label: str,
) -> CreativeArtifactReference:
    source = _verify_reference(source_root, reference, label=label)
    suffix = source.suffix[:16]
    relative = (
        Path("evidence")
        / category
        / f"{reference.sha256}{suffix}"
    )
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if sha256_file(destination) != reference.sha256:
            raise ValueError(f"frozen artifact collision at {destination}")
    else:
        shutil.copyfile(source, destination)
    return CreativeArtifactReference(
        relative_path=relative.as_posix(),
        sha256=reference.sha256,
    )


class CreativeReviewDraft(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-review-draft/v3"] = (
        CREATIVE_REVIEW_DRAFT_VERSION
    )
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    authorized_by: list[str] = Field(min_length=1)
    authorized_at: datetime
    items: list[CreativeGoldItem] = Field(min_length=1)
    candidates: list[CreativeCandidateObservation] = Field(min_length=1)
    judge_records: list[CreativeJudgeRecord] = Field(default_factory=list)
    challenges: list[CreativeChallengeResult] = Field(min_length=1)
    config: CreativeAgentEvaluationConfig = Field(
        default_factory=CreativeAgentEvaluationConfig
    )
    item_artifacts: list[CreativeGoldArtifactSet] = Field(min_length=1)
    candidate_artifacts: list[CreativeCandidateArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_draft(self) -> CreativeReviewDraft:
        if len(self.authorized_by) != len(set(self.authorized_by)):
            raise ValueError("creative review authorizers must be unique")
        items = {item.item_id: item for item in self.items}
        candidates = {item.candidate_id: item for item in self.candidates}
        if len(items) != len(self.items) or len(candidates) != len(self.candidates):
            raise ValueError("creative review draft IDs must be unique")
        test_items = [
            item for item in self.items if item.split.value == "test"
        ]
        if not test_items:
            raise ValueError("creative review draft requires frozen test items")
        if any(
            not item.frozen
            or not item.accepted
            or item.media_origin
            not in {
                CreativeMediaOrigin.CAMERA_ORIGINAL,
                CreativeMediaOrigin.LICENSED_STOCK,
                CreativeMediaOrigin.PUBLISHED_DATASET,
            }
            for item in test_items
        ):
            raise ValueError(
                "creative production review requires accepted frozen real-media test items"
            )
        if any(candidate.item_id not in items for candidate in self.candidates):
            raise ValueError("creative review candidate references an unknown item")
        item_bindings = {item.item_id: item for item in self.item_artifacts}
        candidate_bindings = {
            item.candidate_id: item for item in self.candidate_artifacts
        }
        if set(item_bindings) != set(items):
            raise ValueError("creative review item artifact coverage is incomplete")
        if set(candidate_bindings) != set(candidates):
            raise ValueError("creative review candidate artifact coverage is incomplete")
        for item_id, item in items.items():
            binding = item_bindings[item_id]
            if (
                binding.media.sha256 != item.media_sha256
                or binding.annotation.sha256 != item.annotation_sha256
            ):
                raise ValueError(
                    f"creative review item artifacts do not bind {item_id}"
                )
        for candidate_id, candidate in candidates.items():
            binding = candidate_bindings[candidate_id]
            if binding.output.sha256 != candidate.output_sha256:
                raise ValueError(
                    f"creative review output does not bind {candidate_id}"
                )
            if (
                binding.source_graph.sha256
                != candidate.execution.source_graph_artifact_sha256
            ):
                raise ValueError(
                    f"creative review source graph does not bind {candidate_id}"
                )
            if (
                binding.run_request.sha256
                != candidate.execution.run_request_sha256
            ):
                raise ValueError(
                    f"creative review run request does not bind {candidate_id}"
                )
            if (
                binding.pipeline_result.sha256
                != candidate.execution.pipeline_result_sha256
            ):
                raise ValueError(
                    f"creative review pipeline result does not bind {candidate_id}"
                )
            expected_execution_evidence = {
                stage.value: digest
                for stage, digest in (
                    candidate.execution.stage_evidence_sha256.items()
                )
            }
            observed_execution_evidence = {
                stage: reference.sha256
                for stage, reference in binding.execution_evidence.items()
            }
            if observed_execution_evidence != expected_execution_evidence:
                raise ValueError(
                    f"creative review execution evidence does not bind "
                    f"{candidate_id}"
                )
        review_pairs = build_creative_agent_review_pairs(self.candidates)
        if not review_pairs:
            raise ValueError("creative review draft has no eligible blind pairs")
        pair_ids = {item.id for item in review_pairs}
        if any(record.pair_id not in pair_ids for record in self.judge_records):
            raise ValueError(
                "creative judge records must reference the generated frozen pair plan"
            )
        return self


class CreativeReviewerRegistration(StrictEvaluationModel):
    reviewer: CreativeReviewer
    qualification_attestation: CreativeArtifactReference
    qualification_approved_by: str = Field(min_length=1)
    signed_at: datetime

    @model_validator(mode="after")
    def validate_registration(self) -> CreativeReviewerRegistration:
        if self.qualification_approved_by == self.reviewer.reviewer_id:
            raise ValueError("reviewers cannot approve their own qualification")
        if (
            not self.reviewer.color_vision_screened
            or not self.reviewer.calibrated_display_confirmed
        ):
            raise ValueError(
                "creative reviewers require color-vision screening and a calibrated display"
            )
        return self


class CreativeReviewPanel(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-review-panel/v1"] = (
        CREATIVE_REVIEW_PANEL_VERSION
    )
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    panel_approved_by: list[str] = Field(min_length=1)
    reviewers: list[CreativeReviewerRegistration] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_panel(self) -> CreativeReviewPanel:
        reviewer_ids = [
            item.reviewer.reviewer_id for item in self.reviewers
        ]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            raise ValueError("creative review panel IDs must be unique")
        if len(self.panel_approved_by) != len(set(self.panel_approved_by)):
            raise ValueError("creative review panel approvers must be unique")
        if set(reviewer_ids) & set(self.panel_approved_by):
            raise ValueError(
                "creative review panel approval must be independent of reviewers"
            )
        return self


class CreativeBlindAsset(StrictEvaluationModel):
    asset_id: str = Field(min_length=1)
    output: CreativeArtifactReference


class CreativeBlindReviewPair(StrictEvaluationModel):
    pair_id: str = Field(min_length=1)
    item: CreativeGoldItem
    left: CreativeBlindAsset
    right: CreativeBlindAsset

    @model_validator(mode="after")
    def validate_assets(self) -> CreativeBlindReviewPair:
        if self.left.asset_id == self.right.asset_id:
            raise ValueError("blind review assets must differ")
        return self


class CreativeReviewerAssignment(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-review-assignment/v1"] = (
        CREATIVE_REVIEW_ASSIGNMENT_VERSION
    )
    freeze_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    created_at: datetime
    pairs: list[CreativeBlindReviewPair] = Field(min_length=1)
    instructions: list[str] = Field(
        default_factory=lambda: [
            "Review blind left/right outputs on a calibrated display.",
            (
                "Score every dimension independently; brightness or saturation "
                "is not a proxy for quality."
            ),
            "Reject a pair if either asset is missing, corrupt, or reveals its system identity.",
            "Do not coordinate choices with other reviewers before submission.",
        ]
    )


class CreativeReviewAnswerKey(StrictEvaluationModel):
    pair_id: str = Field(min_length=1)
    source_pair_id: str = Field(min_length=1)
    left_asset_id: str = Field(min_length=1)
    left_candidate_id: str = Field(min_length=1)
    right_asset_id: str = Field(min_length=1)
    right_candidate_id: str = Field(min_length=1)


class CreativeReviewAssignmentBinding(StrictEvaluationModel):
    reviewer_id: str = Field(min_length=1)
    assignment: CreativeArtifactReference
    answer_key: list[CreativeReviewAnswerKey] = Field(min_length=1)


class CreativeReviewFreezeManifest(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-review-freeze/v3"] = (
        CREATIVE_REVIEW_FREEZE_VERSION
    )
    freeze_id: str = Field(min_length=1)
    created_at: datetime
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    draft: CreativeArtifactReference
    panel: CreativeArtifactReference
    item_artifacts: list[CreativeGoldArtifactSet] = Field(min_length=1)
    candidate_artifacts: list[CreativeCandidateArtifact] = Field(min_length=1)
    reviewer_attestations: dict[str, CreativeArtifactReference]
    assignments: list[CreativeReviewAssignmentBinding] = Field(min_length=3)
    status: Literal["pending_independent_expert_submissions"] = (
        "pending_independent_expert_submissions"
    )


class CreativeBlindPairResponse(StrictEvaluationModel):
    pair_id: str = Field(min_length=1)
    left_asset_id: str = Field(min_length=1)
    right_asset_id: str = Field(min_length=1)
    choice: CreativePairChoice
    left_scores: CreativeDimensionScores | None = None
    right_scores: CreativeDimensionScores | None = None
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def validate_response(self) -> CreativeBlindPairResponse:
        if self.left_asset_id == self.right_asset_id:
            raise ValueError("creative blind response assets must differ")
        if self.choice == CreativePairChoice.REJECT:
            if not self.rejection_reason:
                raise ValueError("rejected review responses require a reason")
            if self.left_scores is not None or self.right_scores is not None:
                raise ValueError("rejected review responses cannot include scores")
        elif (
            self.rejection_reason is not None
            or self.left_scores is None
            or self.right_scores is None
        ):
            raise ValueError(
                "accepted review responses require both score vectors and no rejection"
            )
        return self


class CreativeReviewerSubmission(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-review-submission/v1"] = (
        CREATIVE_REVIEW_SUBMISSION_VERSION
    )
    freeze_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    assignment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    submitted_at: datetime
    responses: list[CreativeBlindPairResponse] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_pairs(self) -> CreativeReviewerSubmission:
        pair_ids = [item.pair_id for item in self.responses]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("creative reviewer submission contains duplicate pairs")
        return self


def _artifact_by_item(
    artifacts: list[CreativeGoldArtifactSet],
) -> dict[str, CreativeGoldArtifactSet]:
    return {item.item_id: item for item in artifacts}


def _artifact_by_candidate(
    artifacts: list[CreativeCandidateArtifact],
) -> dict[str, CreativeCandidateArtifact]:
    return {item.candidate_id: item for item in artifacts}


def create_creative_review_freeze(
    draft_path: str | Path,
    panel_path: str | Path,
    output_dir: str | Path,
) -> CreativeReviewFreezeManifest:
    draft_source = Path(draft_path).resolve()
    panel_source = Path(panel_path).resolve()
    root = Path(output_dir).resolve()
    manifest_path = root / "creative-review-freeze.json"
    if manifest_path.exists():
        raise FileExistsError(
            f"creative review freeze already exists: {manifest_path}"
        )
    draft = CreativeReviewDraft.model_validate_json(
        draft_source.read_text(encoding="utf-8")
    )
    panel = CreativeReviewPanel.model_validate_json(
        panel_source.read_text(encoding="utf-8")
    )
    if (
        panel.evaluation_id != draft.evaluation_id
        or panel.dataset_version != draft.dataset_version
    ):
        raise ValueError("creative review draft and panel identities differ")

    root.mkdir(parents=True, exist_ok=True)
    frozen_item_artifacts: list[CreativeGoldArtifactSet] = []
    for binding in draft.item_artifacts:
        frozen_item_artifacts.append(
            CreativeGoldArtifactSet(
                item_id=binding.item_id,
                media=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.media,
                    destination_root=root,
                    category="media",
                    label=f"{binding.item_id} media",
                ),
                annotation=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.annotation,
                    destination_root=root,
                    category="annotations",
                    label=f"{binding.item_id} annotation",
                ),
                license_evidence=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.license_evidence,
                    destination_root=root,
                    category="licenses",
                    label=f"{binding.item_id} license evidence",
                ),
            )
        )
    frozen_candidate_artifacts: list[CreativeCandidateArtifact] = []
    for binding in draft.candidate_artifacts:
        component = _digest_component(binding.candidate_id)
        frozen_candidate_artifacts.append(
            CreativeCandidateArtifact(
                candidate_id=binding.candidate_id,
                output=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.output,
                    destination_root=root,
                    category="candidates",
                    label=f"{binding.candidate_id} candidate output",
                ),
                source_graph=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.source_graph,
                    destination_root=root,
                    category="candidate-source-graphs",
                    label=f"{binding.candidate_id} source graph",
                ),
                run_request=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.run_request,
                    destination_root=root,
                    category=f"candidate-execution/{component}/run-request",
                    label=f"{binding.candidate_id} run request",
                ),
                pipeline_result=_copy_reference(
                    source_root=draft_source.parent,
                    reference=binding.pipeline_result,
                    destination_root=root,
                    category=f"candidate-execution/{component}/pipeline-result",
                    label=f"{binding.candidate_id} pipeline result",
                ),
                execution_evidence={
                    stage: _copy_reference(
                        source_root=draft_source.parent,
                        reference=reference,
                        destination_root=root,
                        category=(
                            f"candidate-execution/{component}/"
                            f"{_digest_component(stage)}"
                        ),
                        label=(
                            f"{binding.candidate_id} {stage} "
                            "execution evidence"
                        ),
                    )
                    for stage, reference in binding.execution_evidence.items()
                },
            )
        )
    frozen_attestations: dict[str, CreativeArtifactReference] = {}
    for registration in panel.reviewers:
        reviewer_id = registration.reviewer.reviewer_id
        frozen_attestations[reviewer_id] = _copy_reference(
            source_root=panel_source.parent,
            reference=registration.qualification_attestation,
            destination_root=root,
            category="reviewer-attestations",
            label=f"{reviewer_id} qualification attestation",
        )

    frozen_draft = draft.model_copy(
        update={
            "item_artifacts": frozen_item_artifacts,
            "candidate_artifacts": frozen_candidate_artifacts,
        }
    )
    frozen_panel = panel.model_copy(
        update={
            "reviewers": [
                registration.model_copy(
                    update={
                        "qualification_attestation": frozen_attestations[
                            registration.reviewer.reviewer_id
                        ]
                    }
                )
                for registration in panel.reviewers
            ]
        }
    )
    draft_copy = root / "frozen-draft.json"
    panel_copy = root / "frozen-panel.json"
    _write_model(draft_copy, frozen_draft)
    _write_model(panel_copy, frozen_panel)
    freeze_digest = canonical_sha256(
        {
            "draft_sha256": sha256_file(draft_copy),
            "panel_sha256": sha256_file(panel_copy),
        }
    )
    freeze_id = f"creative-review:{freeze_digest[:24]}"
    candidate_outputs = _artifact_by_candidate(frozen_candidate_artifacts)
    item_by_id = {item.item_id: item for item in frozen_draft.items}
    pairs = build_creative_agent_review_pairs(frozen_draft.candidates)
    assignments: list[CreativeReviewAssignmentBinding] = []
    created_at = datetime.now(UTC)
    for reviewer_index, registration in enumerate(frozen_panel.reviewers):
        reviewer_id = registration.reviewer.reviewer_id
        public_pairs: list[CreativeBlindReviewPair] = []
        answer_key: list[CreativeReviewAnswerKey] = []
        for pair in pairs:
            public_pair_id = (
                "pair:"
                + canonical_sha256(
                    {
                        "freeze_id": freeze_id,
                        "source_pair_id": pair.id,
                    }
                )[:24]
            )
            parity = int(
                hashlib.sha256(
                    f"{freeze_id}\0{pair.id}".encode()
                ).hexdigest(),
                16,
            ) & 1
            swap = bool(parity ^ (reviewer_index & 1))
            left_candidate_id, right_candidate_id = (
                (pair.candidate_b_id, pair.candidate_a_id)
                if swap
                else (pair.candidate_a_id, pair.candidate_b_id)
            )
            left_asset_id = (
                "asset:"
                + canonical_sha256(
                    {
                        "freeze_id": freeze_id,
                        "reviewer_id": reviewer_id,
                        "pair_id": pair.id,
                        "side": "left",
                        "candidate_sha256": candidate_outputs[
                            left_candidate_id
                        ].output.sha256,
                    }
                )[:24]
            )
            right_asset_id = (
                "asset:"
                + canonical_sha256(
                    {
                        "freeze_id": freeze_id,
                        "reviewer_id": reviewer_id,
                        "pair_id": pair.id,
                        "side": "right",
                        "candidate_sha256": candidate_outputs[
                            right_candidate_id
                        ].output.sha256,
                    }
                )[:24]
            )
            public_pairs.append(
                CreativeBlindReviewPair(
                    pair_id=public_pair_id,
                    item=item_by_id[pair.source_id],
                    left=CreativeBlindAsset(
                        asset_id=left_asset_id,
                        output=candidate_outputs[left_candidate_id].output,
                    ),
                    right=CreativeBlindAsset(
                        asset_id=right_asset_id,
                        output=candidate_outputs[right_candidate_id].output,
                    ),
                )
            )
            answer_key.append(
                CreativeReviewAnswerKey(
                    pair_id=public_pair_id,
                    source_pair_id=pair.id,
                    left_asset_id=left_asset_id,
                    left_candidate_id=left_candidate_id,
                    right_asset_id=right_asset_id,
                    right_candidate_id=right_candidate_id,
                )
            )
        assignment = CreativeReviewerAssignment(
            freeze_id=freeze_id,
            evaluation_id=frozen_draft.evaluation_id,
            dataset_version=frozen_draft.dataset_version,
            reviewer_id=reviewer_id,
            created_at=created_at,
            pairs=public_pairs,
        )
        relative = (
            Path("assignments")
            / f"{_digest_component(reviewer_id)}.json"
        )
        assignment_path = root / relative
        _write_model(assignment_path, assignment)
        assignments.append(
            CreativeReviewAssignmentBinding(
                reviewer_id=reviewer_id,
                assignment=CreativeArtifactReference(
                    relative_path=relative.as_posix(),
                    sha256=sha256_file(assignment_path),
                ),
                answer_key=answer_key,
            )
        )

    manifest = CreativeReviewFreezeManifest(
        freeze_id=freeze_id,
        created_at=created_at,
        evaluation_id=frozen_draft.evaluation_id,
        dataset_version=frozen_draft.dataset_version,
        draft=CreativeArtifactReference(
            relative_path=draft_copy.relative_to(root).as_posix(),
            sha256=sha256_file(draft_copy),
        ),
        panel=CreativeArtifactReference(
            relative_path=panel_copy.relative_to(root).as_posix(),
            sha256=sha256_file(panel_copy),
        ),
        item_artifacts=frozen_item_artifacts,
        candidate_artifacts=frozen_candidate_artifacts,
        reviewer_attestations=frozen_attestations,
        assignments=assignments,
    )
    _write_model(manifest_path, manifest)
    return manifest


def _load_frozen_inputs(
    manifest_path: Path,
) -> tuple[
    CreativeReviewFreezeManifest,
    CreativeReviewDraft,
    CreativeReviewPanel,
]:
    root = manifest_path.parent.resolve()
    manifest = CreativeReviewFreezeManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    draft_path = _verify_reference(root, manifest.draft, label="frozen draft")
    panel_path = _verify_reference(root, manifest.panel, label="frozen panel")
    draft = CreativeReviewDraft.model_validate_json(
        draft_path.read_text(encoding="utf-8")
    )
    panel = CreativeReviewPanel.model_validate_json(
        panel_path.read_text(encoding="utf-8")
    )
    if (
        manifest.evaluation_id != draft.evaluation_id
        or manifest.dataset_version != draft.dataset_version
        or panel.evaluation_id != draft.evaluation_id
        or panel.dataset_version != draft.dataset_version
    ):
        raise ValueError("creative review freeze identities differ")
    for binding in manifest.item_artifacts:
        _verify_reference(root, binding.media, label=f"{binding.item_id} media")
        _verify_reference(
            root,
            binding.annotation,
            label=f"{binding.item_id} annotation",
        )
        _verify_reference(
            root,
            binding.license_evidence,
            label=f"{binding.item_id} license evidence",
        )
    for binding in manifest.candidate_artifacts:
        _verify_reference(
            root,
            binding.output,
            label=f"{binding.candidate_id} candidate",
        )
        _verify_reference(
            root,
            binding.source_graph,
            label=f"{binding.candidate_id} source graph",
        )
        _verify_reference(
            root,
            binding.run_request,
            label=f"{binding.candidate_id} run request",
        )
        _verify_reference(
            root,
            binding.pipeline_result,
            label=f"{binding.candidate_id} pipeline result",
        )
        for stage, reference in binding.execution_evidence.items():
            _verify_reference(
                root,
                reference,
                label=f"{binding.candidate_id} {stage} execution evidence",
            )
    for reviewer_id, reference in manifest.reviewer_attestations.items():
        _verify_reference(
            root,
            reference,
            label=f"{reviewer_id} attestation",
        )
    return manifest, draft, panel


def assemble_creative_production_evaluation(
    freeze_manifest_path: str | Path,
    submission_paths: list[str | Path],
    output_path: str | Path,
) -> CreativeAgentEvaluationBundle:
    freeze_source = Path(freeze_manifest_path).resolve()
    root = freeze_source.parent.resolve()
    destination = Path(output_path).resolve()
    if destination.parent != root:
        raise ValueError(
            "creative production evaluation must be written inside its frozen evidence root"
        )
    production_manifest_path = root / "production-manifest.json"
    if destination.exists() or production_manifest_path.exists():
        raise FileExistsError(
            "creative production evaluation output already exists"
        )
    manifest, draft, panel = _load_frozen_inputs(freeze_source)
    bindings = {item.reviewer_id: item for item in manifest.assignments}
    registrations = {
        item.reviewer.reviewer_id: item for item in panel.reviewers
    }
    submissions: dict[str, tuple[CreativeReviewerSubmission, Path]] = {}
    for value in submission_paths:
        source = Path(value).resolve()
        submission = CreativeReviewerSubmission.model_validate_json(
            source.read_text(encoding="utf-8")
        )
        if submission.reviewer_id in submissions:
            raise ValueError("duplicate creative reviewer submission")
        submissions[submission.reviewer_id] = (submission, source)
    if set(submissions) != set(bindings):
        raise ValueError(
            "creative production assembly requires exactly one submission "
            "from every frozen reviewer"
        )

    reviews: list[CreativePairReview] = []
    source_to_public_pairs: dict[str, str] = {}
    reviewer_attestations: list[CreativeReviewerAttestation] = []
    for reviewer_id, binding in bindings.items():
        submission, _ = submissions[reviewer_id]
        assignment_path = _verify_reference(
            root,
            binding.assignment,
            label=f"{reviewer_id} assignment",
        )
        if submission.assignment_sha256 != binding.assignment.sha256:
            raise ValueError(f"{reviewer_id} submission uses another assignment")
        if (
            submission.freeze_id != manifest.freeze_id
            or submission.evaluation_id != manifest.evaluation_id
            or submission.dataset_version != manifest.dataset_version
        ):
            raise ValueError(f"{reviewer_id} submission identity differs")
        assignment = CreativeReviewerAssignment.model_validate_json(
            assignment_path.read_text(encoding="utf-8")
        )
        expected_pairs = {item.pair_id: item for item in assignment.pairs}
        answer_key = {item.pair_id: item for item in binding.answer_key}
        responses = {item.pair_id: item for item in submission.responses}
        if set(responses) != set(expected_pairs) or set(answer_key) != set(
            expected_pairs
        ):
            raise ValueError(f"{reviewer_id} submission pair coverage differs")
        reviewer_reviews: list[CreativePairReview] = []
        for pair_id, pair in expected_pairs.items():
            response = responses[pair_id]
            key = answer_key[pair_id]
            previous_public = source_to_public_pairs.setdefault(
                key.source_pair_id,
                key.pair_id,
            )
            if previous_public != key.pair_id:
                raise ValueError("creative review pair blinding changed by reviewer")
            if (
                response.left_asset_id != pair.left.asset_id
                or response.right_asset_id != pair.right.asset_id
                or key.left_asset_id != pair.left.asset_id
                or key.right_asset_id != pair.right.asset_id
            ):
                raise ValueError(
                    f"{reviewer_id} response asset identity differs for {pair_id}"
                )
            review = CreativePairReview(
                pair_id=pair_id,
                item_id=pair.item.item_id,
                reviewer_id=reviewer_id,
                displayed_left_candidate_id=key.left_candidate_id,
                displayed_right_candidate_id=key.right_candidate_id,
                choice=response.choice,
                left_scores=response.left_scores,
                right_scores=response.right_scores,
                rejection_reason=response.rejection_reason,
            )
            reviewer_reviews.append(review)
            reviews.append(review)

        submission_relative = (
            Path("reviewer-submissions")
            / f"{_digest_component(reviewer_id)}.json"
        )
        submission_copy = root / submission_relative
        _write_model(submission_copy, submission)
        source_submission = CreativeArtifactReference(
            relative_path=submission_relative.as_posix(),
            sha256=sha256_file(submission_copy),
        )
        response_relative = (
            Path("reviewer-responses")
            / f"{_digest_component(reviewer_id)}.json"
        )
        response_path = root / response_relative
        response = CreativeReviewerResponseEnvelope(
            evaluation_id=manifest.evaluation_id,
            dataset_version=manifest.dataset_version,
            reviewer_id=reviewer_id,
            submitted_at=submission.submitted_at,
            source_submission_sha256=source_submission.sha256,
            reviews=[
                item.model_dump(mode="json")
                for item in sorted(
                    reviewer_reviews,
                    key=lambda item: item.pair_id,
                )
            ],
        )
        _write_model(response_path, response)
        registration = registrations[reviewer_id]
        reviewer_attestations.append(
            CreativeReviewerAttestation(
                reviewer_id=reviewer_id,
                attestation=manifest.reviewer_attestations[reviewer_id],
                source_submission=source_submission,
                review_response=CreativeArtifactReference(
                    relative_path=response_relative.as_posix(),
                    sha256=sha256_file(response_path),
                ),
                qualification_approved_by=(
                    registration.qualification_approved_by
                ),
                years_experience=registration.reviewer.years_experience,
                roles=registration.reviewer.roles,
                color_vision_screened=(
                    registration.reviewer.color_vision_screened
                ),
                calibrated_display_confirmed=(
                    registration.reviewer.calibrated_display_confirmed
                ),
                signed_at=registration.signed_at,
            )
        )

    bundle = CreativeAgentEvaluationBundle(
        evaluation_id=draft.evaluation_id,
        evidence_class=CreativeEvidenceClass.PRODUCTION,
        dataset_version=draft.dataset_version,
        created_at=draft.created_at,
        items=draft.items,
        reviewers=[item.reviewer for item in panel.reviewers],
        candidates=draft.candidates,
        reviews=reviews,
        judge_records=[
            record.model_copy(
                update={
                    "pair_id": source_to_public_pairs[record.pair_id],
                }
            )
            for record in draft.judge_records
        ],
        challenges=draft.challenges,
        production_manifest=CreativeArtifactReference(
            relative_path=production_manifest_path.name,
            sha256="0" * 64,
        ),
        config=draft.config,
    )
    production_manifest = CreativeProductionManifest(
        manifest_id=f"production:{manifest.freeze_id}",
        evaluation_id=draft.evaluation_id,
        dataset_version=draft.dataset_version,
        created_at=datetime.now(UTC),
        authorized_by=draft.authorized_by,
        authorized_at=draft.authorized_at,
        item_artifacts=manifest.item_artifacts,
        candidate_artifacts=manifest.candidate_artifacts,
        reviewer_attestations=reviewer_attestations,
        **creative_bundle_component_digests(bundle),
    )
    _write_model(production_manifest_path, production_manifest)
    bundle = bundle.model_copy(
        update={
            "production_manifest": CreativeArtifactReference(
                relative_path=production_manifest_path.name,
                sha256=sha256_file(production_manifest_path),
            )
        }
    )
    _write_model(destination, bundle)
    return bundle
