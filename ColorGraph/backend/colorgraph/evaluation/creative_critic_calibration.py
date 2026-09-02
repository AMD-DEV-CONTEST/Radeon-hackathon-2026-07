from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from colorgraph.agent.creative_contracts import canonical_sha256
from colorgraph.agent.creative_critic import (
    CalibrationPreference,
    CreativeModelIdentity,
    CriticCalibrationGate,
    CriticCalibrationThresholds,
    CriticExpertCalibrationRecord,
    CriticModelRelationship,
    CriticViolationCode,
    PairwiseVisualCriticReport,
    build_critic_calibration_gate,
)
from colorgraph.evaluation.creative_agent import (
    CreativeAgentEvaluationBundle,
    CreativeEvidenceClass,
    CreativePairChoice,
)
from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    sha256_file,
    verify_creative_production_manifest,
)
from colorgraph.evaluation.models import StrictEvaluationModel

CREATIVE_CRITIC_CALIBRATION_SOURCE_VERSION = (
    "colorgraph.creative-critic-calibration-source/v1"
)
CREATIVE_CRITIC_CALIBRATION_AUDIT_VERSION = (
    "colorgraph.creative-critic-calibration-audit/v1"
)


class CreativeCriticReportBinding(StrictEvaluationModel):
    record_id: str = Field(min_length=1)
    pair_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    left_candidate_id: str = Field(min_length=1)
    right_candidate_id: str = Field(min_length=1)
    report: CreativeArtifactReference

    @model_validator(mode="after")
    def validate_pair(self) -> CreativeCriticReportBinding:
        if self.left_candidate_id == self.right_candidate_id:
            raise ValueError("Critic calibration candidates must differ")
        return self


class CreativeCriticCalibrationSource(StrictEvaluationModel):
    schema_version: Literal[
        "colorgraph.creative-critic-calibration-source/v1"
    ] = CREATIVE_CRITIC_CALIBRATION_SOURCE_VERSION
    calibration_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    authorized_by: list[str] = Field(min_length=1)
    authorized_at: datetime
    evaluation_bundle: CreativeArtifactReference
    deployment_critic_identity: CreativeModelIdentity
    director_identity: CreativeModelIdentity
    thresholds: CriticCalibrationThresholds = Field(
        default_factory=CriticCalibrationThresholds
    )
    reports: list[CreativeCriticReportBinding] = Field(min_length=10)

    @model_validator(mode="after")
    def validate_source(self) -> CreativeCriticCalibrationSource:
        if len(self.authorized_by) != len(set(self.authorized_by)):
            raise ValueError("Critic calibration authorizers must be unique")
        record_ids = [item.record_id for item in self.reports]
        report_digests = [item.report.sha256 for item in self.reports]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Critic calibration record IDs must be unique")
        if len(report_digests) != len(set(report_digests)):
            raise ValueError(
                "Critic calibration cannot count the same report more than once"
            )
        return self


class CreativeCriticCalibrationAudit(StrictEvaluationModel):
    schema_version: Literal[
        "colorgraph.creative-critic-calibration-audit/v1"
    ] = CREATIVE_CRITIC_CALIBRATION_AUDIT_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    calibration_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_id: str | None = None
    dataset_version: str | None = None
    production_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    qualified_reviewer_count: int = Field(ge=0)
    checked_report_count: int = Field(ge=0)
    independent_record_count: int = Field(ge=0)
    self_evaluation_record_count: int = Field(ge=0)
    derived_records_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    gate: CriticCalibrationGate | None
    issues: list[str]
    evidence_integrity_passed: bool
    calibration_authorized: bool


@dataclass(frozen=True, slots=True)
class LoadedCreativeCriticCalibration:
    source: CreativeCriticCalibrationSource
    audit: CreativeCriticCalibrationAudit
    gate: CriticCalibrationGate | None


def _resolve_reference(
    root: Path,
    reference: CreativeArtifactReference,
) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / reference.relative_path).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError(
            "Critic calibration artifact escapes its source root: "
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


def _review_winner(
    bundle: CreativeAgentEvaluationBundle,
    pair_id: str,
) -> tuple[str | None, set[str], str | None]:
    reviews = [item for item in bundle.reviews if item.pair_id == pair_id]
    if not reviews:
        return None, set(), "pair has no expert reviews"
    candidate_set = {
        reviews[0].displayed_left_candidate_id,
        reviews[0].displayed_right_candidate_id,
    }
    reviewer_ids: set[str] = set()
    votes: Counter[str] = Counter()
    tie_votes = 0
    for review in reviews:
        reviewer_ids.add(review.reviewer_id)
        if {
            review.displayed_left_candidate_id,
            review.displayed_right_candidate_id,
        } != candidate_set:
            return None, reviewer_ids, "pair candidate set changed by reviewer"
        if review.choice == CreativePairChoice.LEFT:
            votes[review.displayed_left_candidate_id] += 1
        elif review.choice == CreativePairChoice.RIGHT:
            votes[review.displayed_right_candidate_id] += 1
        elif review.choice == CreativePairChoice.TIE:
            tie_votes += 1
    if len(reviewer_ids) < bundle.config.minimum_reviewers:
        return None, reviewer_ids, "pair has fewer than three qualified reviewers"
    if not votes:
        return None, reviewer_ids, None
    ranked = votes.most_common()
    if (
        len(ranked) > 1
        and ranked[0][1] == ranked[1][1]
        or tie_votes > ranked[0][1]
    ):
        return None, reviewer_ids, None
    return ranked[0][0], reviewer_ids, None


def _preference(
    candidate_id: str | None,
    *,
    left_candidate_id: str,
    right_candidate_id: str,
) -> CalibrationPreference:
    if candidate_id is None:
        return CalibrationPreference.TIE
    if candidate_id == left_candidate_id:
        return CalibrationPreference.LEFT
    if candidate_id == right_candidate_id:
        return CalibrationPreference.RIGHT
    raise ValueError("calibration preference selected a candidate outside the pair")


def _same_model(
    left: CreativeModelIdentity,
    right: CreativeModelIdentity,
) -> bool:
    return (
        left.provider_id == right.provider_id
        and left.model_id == right.model_id
        and left.model_revision == right.model_revision
    )


def load_creative_critic_calibration(
    path: str | Path,
    *,
    expected_gate_sha256: str | None = None,
) -> LoadedCreativeCriticCalibration:
    source_path = Path(path).resolve()
    source = CreativeCriticCalibrationSource.model_validate_json(
        source_path.read_text(encoding="utf-8")
    )
    source_sha256 = sha256_file(source_path)
    root = source_path.parent.resolve()
    issues: list[str] = []
    evaluation_id: str | None = None
    dataset_version: str | None = None
    manifest_sha256: str | None = None
    qualified_reviewer_count = 0
    records: list[CriticExpertCalibrationRecord] = []
    checked_reports = 0

    try:
        bundle_path = _verify_reference(
            root,
            source.evaluation_bundle,
            label="expert evaluation bundle",
        )
        bundle = CreativeAgentEvaluationBundle.model_validate_json(
            bundle_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        issues.append(f"expert evaluation bundle is invalid: {exc}")
        bundle = None

    if bundle is not None:
        evaluation_id = bundle.evaluation_id
        dataset_version = bundle.dataset_version
        qualified_reviewer_count = sum(
            reviewer.color_vision_screened
            and reviewer.calibrated_display_confirmed
            for reviewer in bundle.reviewers
        )
        if bundle.evidence_class != CreativeEvidenceClass.PRODUCTION:
            issues.append("Critic calibration requires production expert evidence")
        if bundle.production_manifest is None:
            issues.append("expert evaluation has no production manifest")
        else:
            manifest_path = (
                bundle_path.parent / bundle.production_manifest.relative_path
            ).resolve()
            audit = verify_creative_production_manifest(
                bundle,
                manifest_path,
                expected_manifest_sha256=bundle.production_manifest.sha256,
            )
            manifest_sha256 = audit.manifest_sha256
            if not audit.passed:
                issues.extend(
                    f"expert production evidence: {issue}"
                    for issue in audit.issues
                )
        reviewer_ids = {item.reviewer_id for item in bundle.reviewers}
        if set(source.authorized_by) & reviewer_ids:
            issues.append(
                "Critic calibration authorization must be independent of reviewers"
            )
        if qualified_reviewer_count < bundle.config.minimum_reviewers:
            issues.append("expert evaluation has fewer than three qualified reviewers")

    relationship_pairs: dict[
        CriticModelRelationship,
        set[str],
    ] = defaultdict(set)
    for binding in source.reports:
        try:
            report_path = _verify_reference(
                root,
                binding.report,
                label=f"Critic report {binding.record_id}",
            )
            report = PairwiseVisualCriticReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            issues.append(f"{binding.record_id} report is invalid: {exc}")
            continue
        checked_reports += 1
        relationship = (
            CriticModelRelationship.SAME_AS_DIRECTOR
            if report.self_evaluation_model
            else CriticModelRelationship.INDEPENDENT
        )
        if binding.pair_id in relationship_pairs[relationship]:
            issues.append(
                f"{binding.record_id} duplicates a pair within {relationship.value}"
            )
        relationship_pairs[relationship].add(binding.pair_id)
        if report.pair_id != binding.pair_id:
            issues.append(f"{binding.record_id} report pair_id differs")
        if report.director_identity != source.director_identity:
            issues.append(f"{binding.record_id} Director identity differs")
        critic_identity_matches = (
            _same_model(report.critic_identity, source.director_identity)
            if relationship == CriticModelRelationship.SAME_AS_DIRECTOR
            else report.critic_identity == source.deployment_critic_identity
        )
        if not critic_identity_matches:
            issues.append(f"{binding.record_id} Critic identity differs")
        candidate_set = {
            binding.left_candidate_id,
            binding.right_candidate_id,
        }
        if {item.candidate_id for item in report.critiques} != candidate_set:
            issues.append(f"{binding.record_id} report candidates differ")
        if bundle is None:
            continue
        winner, reviewer_ids, winner_issue = _review_winner(
            bundle,
            binding.pair_id,
        )
        if winner_issue is not None:
            issues.append(f"{binding.record_id} expert consensus: {winner_issue}")
            continue
        pair_reviews = [
            item for item in bundle.reviews if item.pair_id == binding.pair_id
        ]
        if not pair_reviews:
            continue
        if any(item.item_id != binding.item_id for item in pair_reviews):
            issues.append(f"{binding.record_id} expert item identity differs")
            continue
        review_candidate_set = {
            pair_reviews[0].displayed_left_candidate_id,
            pair_reviews[0].displayed_right_candidate_id,
        }
        if review_candidate_set != candidate_set:
            issues.append(f"{binding.record_id} expert pair candidates differ")
            continue
        if any(
            reviewer_id
            not in {item.reviewer_id for item in bundle.reviewers}
            for reviewer_id in reviewer_ids
        ):
            issues.append(f"{binding.record_id} has an unknown expert reviewer")
            continue
        violations = [
            violation.code
            for output_audit in report.output_audits
            for violation in output_audit.violations
        ]
        try:
            records.append(
                CriticExpertCalibrationRecord(
                    record_id=binding.record_id,
                    pair_id=binding.pair_id,
                    source_id=binding.item_id,
                    model_relationship=relationship,
                    critic_preference=_preference(
                        report.preferred_candidate_id,
                        left_candidate_id=binding.left_candidate_id,
                        right_candidate_id=binding.right_candidate_id,
                    ),
                    expert_preference=_preference(
                        winner,
                        left_candidate_id=binding.left_candidate_id,
                        right_candidate_id=binding.right_candidate_id,
                    ),
                    position_swap_consistent=report.position_swap_consistent,
                    shortcut_violation=(
                        CriticViolationCode.BIAS_SHORTCUT in violations
                    ),
                    unsupported_evidence=any(
                        code
                        in {
                            CriticViolationCode.UNKNOWN_EVIDENCE,
                            CriticViolationCode.CROSS_LABEL_EVIDENCE,
                            CriticViolationCode.MISSING_CANDIDATE_EVIDENCE,
                            CriticViolationCode.MISSING_COUNTEREVIDENCE,
                            CriticViolationCode.PAIRWISE_EVIDENCE,
                        }
                        for code in violations
                    ),
                )
            )
        except ValueError as exc:
            issues.append(f"{binding.record_id} preference is invalid: {exc}")

    gate = None
    if not issues and len(records) == len(source.reports):
        gate = build_critic_calibration_gate(
            records,
            deployment_critic_identity=source.deployment_critic_identity,
            director_identity=source.director_identity,
            thresholds=source.thresholds,
        )
        if expected_gate_sha256 is not None and canonical_sha256(
            gate
        ) != expected_gate_sha256:
            issues.append(
                "Critic calibration gate differs from the immutable Agent run"
            )
            gate = None
    independent_count = sum(
        item.model_relationship == CriticModelRelationship.INDEPENDENT
        for item in records
    )
    self_count = sum(
        item.model_relationship == CriticModelRelationship.SAME_AS_DIRECTOR
        for item in records
    )
    audit = CreativeCriticCalibrationAudit(
        calibration_id=source.calibration_id,
        source_sha256=source_sha256,
        evaluation_id=evaluation_id,
        dataset_version=dataset_version,
        production_manifest_sha256=manifest_sha256,
        qualified_reviewer_count=qualified_reviewer_count,
        checked_report_count=checked_reports,
        independent_record_count=independent_count,
        self_evaluation_record_count=self_count,
        derived_records_sha256=(
            canonical_sha256(
                [item.model_dump(mode="json") for item in records]
            )
            if records
            else None
        ),
        gate=gate,
        issues=issues,
        evidence_integrity_passed=not issues and gate is not None,
        calibration_authorized=(
            not issues and gate is not None and gate.authorized
        ),
    )
    return LoadedCreativeCriticCalibration(
        source=source,
        audit=audit,
        gate=gate,
    )


def audit_creative_critic_calibration_file(
    input_path: str | Path,
    output_path: str | Path,
) -> CreativeCriticCalibrationAudit:
    loaded = load_creative_critic_calibration(input_path)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        loaded.audit.model_dump_json(indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return loaded.audit
