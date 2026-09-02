from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy import text
from sqlalchemy.orm import Session

from creative_hub.db.models import (
    ArtifactRecordRow,
    QCCalibrationReportRecord,
    QCCandidateVersionRecord,
    QCCertificationEventRecord,
    QCEvaluationFactRecord,
    QCGateDecisionRecord,
    QCGatePolicySnapshotRecord,
    QCGoldDatasetRevisionRecord,
    QCPromptRevisionRecord,
)
from creative_hub.db.repositories import SelectionRepository
from creative_hub.qc_calibration import (
    CalibrationReport,
    CertificationStatus,
    EvaluatorMaturity,
    EvaluatorCertification,
    GoldDatasetRevision,
    build_trial_evaluator_bundle,
    trial_evaluator_rubrics,
)
from creative_hub.quality import (
    CandidateVersion,
    EvaluatorBundle,
    GateOutcome,
    GatePolicySnapshot,
    QCEvaluation,
    QCPromptRevision,
    QualityError,
    QualityStage,
)


class QualityRepository:
    """Append-only PostgreSQL/SQLAlchemy authority for QC facts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def seed_trial_evaluator_bundles(
        self,
        *,
        project_id: UUID,
        created_by_actor: str,
        model_name: str,
        model_version: str,
        implementation_digest: str,
    ) -> tuple[EvaluatorBundle, ...]:
        """Idempotently seed v1 trial prompts and freeze exact bundles."""

        bundles = []
        for rubric in trial_evaluator_rubrics():
            prompt = self.create_prompt_revision(
                project_id=project_id,
                prompt_key=rubric.prompt_key,
                stage=rubric.stage,
                prompt_text=rubric.prompt_text,
                created_by_actor=created_by_actor,
                command_idempotency_key=(
                    f"shidu-trial-evaluator-prompt:v1:{rubric.stage.value}"
                ),
            )
            bundles.append(
                build_trial_evaluator_bundle(
                    project_id=project_id,
                    prompt=prompt,
                    rubric=rubric,
                    model_name=model_name,
                    model_version=model_version,
                    implementation_digest=implementation_digest,
                )
            )
        return tuple(bundles)

    def create_prompt_revision(
        self,
        *,
        project_id: UUID,
        prompt_key: str,
        stage: QualityStage,
        prompt_text: str,
        created_by_actor: str,
        expected_parent_revision_id: UUID | None = None,
        command_idempotency_key: str | None = None,
    ) -> QCPromptRevision:
        if command_idempotency_key is not None and not (
            1 <= len(command_idempotency_key) <= 255
        ):
            raise QualityError("prompt idempotency key length is invalid")
        if (
            command_idempotency_key is not None
            and self.session.get_bind().dialect.name == "postgresql"
        ):
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:identity, 0))"
                ),
                {
                    "identity": (
                        "qc-prompt-command:"
                        f"{project_id}:{command_idempotency_key}"
                    )
                },
            )
        replay = (
            None
            if command_idempotency_key is None
            else self.session.scalar(
                select(QCPromptRevisionRecord).where(
                    QCPromptRevisionRecord.project_id == project_id,
                    QCPromptRevisionRecord.command_idempotency_key
                    == command_idempotency_key,
                )
            )
        )
        if replay is not None:
            if (
                replay.prompt_key != prompt_key
                or replay.stage != stage.value
                or replay.prompt_text != prompt_text
                or (
                    expected_parent_revision_id is not None
                    and replay.parent_revision_id
                    != expected_parent_revision_id
                )
            ):
                raise QualityError(
                    "prompt idempotency key belongs to a different request"
                )
            return QCPromptRevision(
                prompt_revision_id=replay.id,
                project_id=replay.project_id,
                prompt_key=replay.prompt_key,
                stage=QualityStage(replay.stage),
                revision=replay.revision,
                prompt_text=replay.prompt_text,
                parent_revision_id=replay.parent_revision_id,
                created_by_actor=replay.created_by_actor,
                created_at=replay.created_at,
                prompt_digest=replay.prompt_digest,
            )
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:identity, 0))"
                ),
                {
                    "identity": (
                        f"qc-prompt:{project_id}:{prompt_key}:{stage.value}"
                    )
                },
            )
        # The advisory lock above already serializes the revision counter.
        # Do not add FOR UPDATE here: PostgreSQL requires UPDATE privilege for
        # row-locking reads, while QC facts intentionally expose only append.
        latest = self.session.scalar(
            select(QCPromptRevisionRecord)
            .where(
                QCPromptRevisionRecord.project_id == project_id,
                QCPromptRevisionRecord.prompt_key == prompt_key,
                QCPromptRevisionRecord.stage == stage.value,
            )
            .order_by(desc(QCPromptRevisionRecord.revision))
            .limit(1)
        )
        if expected_parent_revision_id is not None and (
            latest is None or latest.id != expected_parent_revision_id
        ):
            raise QualityError(
                "prompt parent is not the current immutable revision"
            )
        revision = QCPromptRevision(
            project_id=project_id,
            prompt_key=prompt_key,
            stage=stage,
            revision=1 if latest is None else latest.revision + 1,
            prompt_text=prompt_text,
            parent_revision_id=None if latest is None else latest.id,
            created_by_actor=created_by_actor,
        )
        self.session.add(
            QCPromptRevisionRecord(
                id=revision.prompt_revision_id,
                project_id=revision.project_id,
                prompt_key=revision.prompt_key,
                stage=revision.stage.value,
                revision=revision.revision,
                prompt_text=revision.prompt_text,
                prompt_digest=revision.prompt_digest,
                parent_revision_id=revision.parent_revision_id,
                created_by_actor=revision.created_by_actor,
                command_idempotency_key=command_idempotency_key,
                created_at=revision.created_at,
            )
        )
        self.session.flush()
        return revision

    def store_policy(self, policy: GatePolicySnapshot) -> None:
        existing = self.session.get(
            QCGatePolicySnapshotRecord,
            policy.policy_snapshot_id,
        )
        if existing is not None:
            if (
                existing.policy_digest != policy.policy_digest
                or existing.gate_key != policy.gate_key
            ):
                raise QualityError("policy snapshot identity conflict")
            return
        prompt = self.session.scalar(
            select(QCPromptRevisionRecord).where(
                QCPromptRevisionRecord.id == policy.prompt_revision_id,
                QCPromptRevisionRecord.project_id == policy.project_id,
                QCPromptRevisionRecord.stage == policy.stage.value,
            )
        )
        if prompt is None:
            raise QualityError("gate policy prompt revision not found")
        self.session.add(
            QCGatePolicySnapshotRecord(
                id=policy.policy_snapshot_id,
                project_id=policy.project_id,
                workflow_run_id=policy.workflow_run_id,
                stage=policy.stage.value,
                gate_key=policy.gate_key,
                review_mode=policy.review_mode.value,
                exhaustion_policy=policy.exhaustion_policy.value,
                machine_qc_required=policy.machine_qc_required,
                budget=policy.budget.model_dump(mode="json"),
                ranking_revision=policy.ranking_revision,
                ranking_weights=policy.ranking_weights,
                prompt_revision_id=policy.prompt_revision_id,
                rubric_revision_id=policy.rubric_revision_id,
                evaluator_bundle_digest=policy.evaluator_bundle_digest,
                policy_digest=policy.policy_digest,
                created_at=policy.created_at,
            )
        )
        self.session.flush()

    def store_evaluation(self, evaluation: QCEvaluation) -> None:
        existing = self.session.get(QCEvaluationFactRecord, evaluation.evaluation_id)
        if existing is not None:
            if (
                existing.evaluation_digest != evaluation.evaluation_digest
                or existing.gate_key != evaluation.gate_key
            ):
                raise QualityError("evaluation identity conflict")
            return
        artifact = self.session.scalar(
            select(ArtifactRecordRow).where(
                ArtifactRecordRow.id == evaluation.artifact.artifact_id,
                ArtifactRecordRow.project_id == evaluation.project_id,
                ArtifactRecordRow.operation_run_id
                == evaluation.artifact.operation_run_id,
                ArtifactRecordRow.operation_attempt_id
                == evaluation.artifact.operation_attempt_id,
                ArtifactRecordRow.content_digest
                == evaluation.artifact.content_digest,
                ArtifactRecordRow.status == "COMMITTED",
            )
        )
        if artifact is None:
            raise QualityError(
                "QC evaluation requires an exact committed artifact"
            )
        prompt = self.session.scalar(
            select(QCPromptRevisionRecord).where(
                QCPromptRevisionRecord.id
                == evaluation.evaluator.prompt_revision_id,
                QCPromptRevisionRecord.project_id == evaluation.project_id,
                QCPromptRevisionRecord.prompt_digest
                == evaluation.evaluator.prompt_digest,
            )
        )
        if prompt is None:
            raise QualityError("QC evaluation prompt binding is unavailable")
        self.session.add(
            QCEvaluationFactRecord(
                id=evaluation.evaluation_id,
                project_id=evaluation.project_id,
                workflow_run_id=evaluation.workflow_run_id,
                stage=evaluation.stage.value,
                gate_key=evaluation.gate_key,
                artifact_id=evaluation.artifact.artifact_id,
                artifact_digest=evaluation.artifact.content_digest,
                artifact_operation_run_id=(
                    evaluation.artifact.operation_run_id
                ),
                artifact_operation_attempt_id=(
                    evaluation.artifact.operation_attempt_id
                ),
                evidence_pack_id=evaluation.evidence_pack.evidence_pack_id,
                evidence_pack_digest=evaluation.evidence_pack.content_digest,
                expected_selection_version=(
                    evaluation.expected_selection_version
                ),
                prompt_revision_id=(
                    evaluation.evaluator.prompt_revision_id
                ),
                prompt_digest=evaluation.evaluator.prompt_digest,
                rubric_revision_id=evaluation.evaluator.rubric_revision_id,
                rubric_digest=evaluation.evaluator.rubric_digest,
                model_name=evaluation.evaluator.model_name,
                model_version=evaluation.evaluator.model_version,
                implementation_digest=(
                    evaluation.evaluator.implementation_digest
                ),
                evaluator_bundle_digest=(
                    evaluation.evaluator.bundle_digest
                ),
                judgment=evaluation.judgment.value,
                quality_score=round(evaluation.quality_score * 10_000),
                confidence=round(evaluation.confidence * 1_000_000),
                defects=[
                    item.model_dump(mode="json")
                    for item in evaluation.defects
                ],
                recommended_actions=list(evaluation.recommended_actions),
                repair_result=evaluation.repair_result.model_dump(mode="json"),
                h3_qc=(
                    evaluation.h3_qc.model_dump(mode="json")
                    if evaluation.h3_qc is not None
                    else None
                ),
                evaluation_digest=evaluation.evaluation_digest,
                evaluated_at=evaluation.evaluated_at,
            )
        )
        self.session.flush()

    def store_candidate(self, candidate: CandidateVersion) -> None:
        existing = self.session.get(QCCandidateVersionRecord, candidate.candidate_id)
        if existing is not None:
            if (
                existing.candidate_digest != candidate.candidate_digest
                or existing.gate_key != candidate.gate_key
            ):
                raise QualityError("candidate identity conflict")
            return
        evaluation = self.session.get(
            QCEvaluationFactRecord,
            candidate.evaluation.evaluation_id,
        )
        if evaluation is None:
            raise QualityError("candidate evaluation is not persisted")
        self.session.add(
            QCCandidateVersionRecord(
                id=candidate.candidate_id,
                project_id=candidate.project_id,
                workflow_run_id=candidate.workflow_run_id,
                stage=candidate.stage.value,
                gate_key=candidate.gate_key,
                ordinal=candidate.ordinal,
                artifact_id=candidate.artifact.artifact_id,
                artifact_digest=candidate.artifact.content_digest,
                evaluation_id=candidate.evaluation.evaluation_id,
                generation_usage=candidate.generation_usage.model_dump(
                    mode="json"
                ),
                candidate_digest=candidate.candidate_digest,
                created_at=candidate.created_at,
            )
        )
        self.session.flush()

    def store_gold_revision(self, dataset: GoldDatasetRevision) -> None:
        existing = self.session.get(
            QCGoldDatasetRevisionRecord,
            dataset.dataset_revision_id,
        )
        if existing is not None:
            if existing.dataset_digest != dataset.dataset_digest:
                raise QualityError("Gold revision identity conflict")
            return
        self.session.add(
            QCGoldDatasetRevisionRecord(
                id=dataset.dataset_revision_id,
                project_id=dataset.project_id,
                dataset_key=dataset.dataset_key,
                revision=dataset.revision,
                parent_revision_id=dataset.parent_revision_id,
                items=[
                    item.model_dump(mode="json") for item in dataset.items
                ],
                dataset_digest=dataset.dataset_digest,
                created_by_actor=dataset.created_by_actor,
                created_at=dataset.created_at,
            )
        )
        self.session.flush()

    def store_calibration_report(self, report: CalibrationReport) -> None:
        existing = self.session.get(
            QCCalibrationReportRecord,
            report.report_id,
        )
        if existing is not None:
            return
        metrics = report.model_dump(
            mode="json",
            include={
                "sample_count",
                "severe_false_acceptance_rate",
                "false_acceptance_rate",
                "false_rejection_rate",
                "evidence_localization_rate",
                "repair_success_rate",
                "average_cost_micros",
            },
        )
        self.session.add(
            QCCalibrationReportRecord(
                id=report.report_id,
                project_id=report.project_id,
                stage=report.stage.value,
                gold_dataset_revision_id=report.gold_dataset_revision_id,
                gold_dataset_digest=report.gold_dataset_digest,
                evaluator_bundle_digest=report.evaluator_bundle_digest,
                metrics=metrics,
                passed=report.passed,
                failures=list(report.failures),
            )
        )
        self.session.flush()

    def store_certification(
        self,
        certification: EvaluatorCertification,
    ) -> None:
        report = self.session.scalar(
            select(QCCalibrationReportRecord).where(
                QCCalibrationReportRecord.id
                == certification.calibration_report_id,
                QCCalibrationReportRecord.project_id
                == certification.project_id,
                QCCalibrationReportRecord.gold_dataset_revision_id
                == certification.gold_dataset_revision_id,
                QCCalibrationReportRecord.evaluator_bundle_digest
                == certification.evaluator_bundle_digest,
            )
        )
        if report is None:
            raise QualityError("certification calibration report not found")
        if (
            certification.status is CertificationStatus.CERTIFIED
            and not report.passed
        ):
            raise QualityError("failed calibration cannot be persisted as certified")
        self.session.add(
            QCCertificationEventRecord(
                id=certification.certification_id,
                project_id=certification.project_id,
                stage=certification.stage.value,
                evaluator_bundle_digest=(
                    certification.evaluator_bundle_digest
                ),
                calibration_report_id=certification.calibration_report_id,
                gold_dataset_revision_id=(
                    certification.gold_dataset_revision_id
                ),
                status=certification.status.value,
                issued_by_actor=certification.issued_by_actor,
                created_at=certification.issued_at,
            )
        )
        self.session.flush()

    def is_certified(
        self,
        *,
        project_id: UUID,
        stage: QualityStage,
        evaluator_bundle_digest: str,
    ) -> bool:
        return (
            self.certification_status(
                project_id=project_id,
                stage=stage,
                evaluator_bundle_digest=evaluator_bundle_digest,
            )
            is EvaluatorMaturity.CERTIFIED
        )

    def certification_status(
        self,
        *,
        project_id: UUID,
        stage: QualityStage,
        evaluator_bundle_digest: str,
    ) -> EvaluatorMaturity:
        event = self.session.scalar(
            select(QCCertificationEventRecord)
            .where(
                QCCertificationEventRecord.project_id == project_id,
                QCCertificationEventRecord.stage == stage.value,
                QCCertificationEventRecord.evaluator_bundle_digest
                == evaluator_bundle_digest,
            )
            .order_by(
                desc(QCCertificationEventRecord.created_at),
                desc(QCCertificationEventRecord.id),
            )
            .limit(1)
        )
        if event is None:
            return EvaluatorMaturity.SHADOW
        return EvaluatorMaturity(event.status)

    def append_gate_outcome(
        self,
        *,
        policy: GatePolicySnapshot,
        outcome: GateOutcome,
        sequence: int,
    ) -> None:
        if outcome.stage != policy.stage:
            raise QualityError("gate outcome/policy stage mismatch")
        if outcome.gate_key != policy.gate_key:
            raise QualityError("gate outcome/policy gate mismatch")
        self.session.add(
            QCGateDecisionRecord(
                project_id=policy.project_id,
                workflow_run_id=policy.workflow_run_id,
                stage=policy.stage.value,
                gate_key=policy.gate_key,
                policy_snapshot_id=policy.policy_snapshot_id,
                candidate_id=outcome.candidate_id,
                decision_sequence=sequence,
                outcome=outcome.kind.value,
                expected_selection_version=(
                    outcome.expected_selection_version
                ),
                payload=outcome.model_dump(mode="json"),
            )
        )
        self.session.flush()


class PostgresSelectionSealer:
    """GateEngine SelectionSealer adapter backed by existing durable CAS."""

    def __init__(
        self,
        *,
        session: Session,
        project_id: UUID,
        selection_head_id: UUID,
        actor_id: str,
        command_prefix: str,
    ) -> None:
        self._repository = SelectionRepository(session)
        self._project_id = project_id
        self._selection_head_id = selection_head_id
        self._actor_id = actor_id
        self._command_prefix = command_prefix

    def seal(
        self,
        *,
        candidate: CandidateVersion,
        expected_selection_version: int,
        decision: str,
        reason: str,
    ) -> None:
        self._repository.compare_and_set(
            selection_head_id=self._selection_head_id,
            project_id=self._project_id,
            expected_state_version=expected_selection_version,
            selected_operation_run_id=(
                candidate.artifact.operation_run_id
            ),
            selected_attempt_id=(
                candidate.artifact.operation_attempt_id
            ),
            artifact_id=candidate.artifact.artifact_id,
            artifact_digest=candidate.artifact.content_digest,
            decision=decision,
            command_idempotency_key=(
                f"{self._command_prefix}:{candidate.candidate_id}:{decision}"
            ),
            created_by_actor=self._actor_id,
            payload={
                "candidate_id": str(candidate.candidate_id),
                "evaluation_id": str(candidate.evaluation.evaluation_id),
                "evaluation_digest": candidate.evaluation.evaluation_digest,
                "policy_stage": candidate.stage.value,
            },
            reason=reason,
            seal=True,
        )


class DatabaseCertificationAuthority:
    """Restart-safe certification lookup for GateEngine."""

    def __init__(self, session: Session) -> None:
        self._repository = QualityRepository(session)

    def is_certified(self, bundle: EvaluatorBundle) -> bool:
        return self._repository.is_certified(
            project_id=bundle.project_id,
            stage=bundle.stage,
            evaluator_bundle_digest=bundle.bundle_digest,
        )
