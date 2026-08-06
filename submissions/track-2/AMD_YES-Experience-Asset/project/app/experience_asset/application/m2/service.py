"""Deterministic, source-linked M2 application service."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import (
    Milestone,
    MilestoneState,
    QuestionState,
)
from app.experience_asset.domain.m2 import (
    ConflictingTimeMomentV1,
    CriticalMomentMapV1,
    KnownTimeMomentV1,
    M2ConfirmRequestV1,
    M2EditRequestV1,
    M2WorkspaceV1,
    MissingTimeMomentV1,
)
from app.experience_asset.domain.models import ExperienceAssetV1
from app.experience_asset.inference.models import M2SemanticRole
from app.experience_asset.persistence import SQLiteAssetRepository, StorageConflictError

from .projection import project_m2

_TIME = re.compile(
    r"(当天|当日|同一天|随后|之后|后来|第一次|最初|"
    r"(?:约|大约|大概)?[一二两三四五六七八九十百两\d]+(?:个)?(?:天|周|星期|月)|"
    r"\b(?:same day|that day|first|then|later|afterwards|"
    r"(?:about )?\d+ (?:days?|weeks?|months?))\b)",
    re.IGNORECASE,
)


def _criticality_reason(*, cue: bool, change: bool, surprise: bool) -> str:
    roles = [
        label
        for matched, label in (
            (cue, "a cue"),
            (change, "a change or turning point"),
            (surprise, "a surprise"),
        )
        if matched
    ]
    if not roles:
        return (
            "The local semantic proposal assigns no cue, change, or surprise role "
            "to this source-linked event; the user must decide whether it is critical."
        )
    return (
        f"The local semantic proposal identifies {', '.join(roles)} in the "
        "source-linked wording; "
        "the user must decide whether the event is critical."
    )


class M2ContractError(ValueError):
    pass


class M2CriticalMomentService:
    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def validate_create(
        self,
        asset_id: UUID,
        expected_m1_version_id: UUID,
    ) -> ExperienceAssetV1:
        """Return the exact accepted M1 input or fail before a workflow starts."""

        current = self.repository.get_current(asset_id)
        if current.version_id != expected_m1_version_id:
            raise StorageConflictError("current M1 changed; reload before generating M2")
        if current.milestone_states[Milestone.M1] not in {
            MilestoneState.CONFIRMED,
            MilestoneState.COMPLETE_WITH_GAPS,
        }:
            raise M2ContractError("M2 requires an accepted M1")
        return current

    def create_for_run(
        self,
        asset_id: UUID,
        *,
        expected_m1_version_id: UUID,
        run_id: UUID,
        semantic_roles: dict[UUID, frozenset[M2SemanticRole]],
    ) -> M2WorkspaceV1:
        """Persist one M2 effect for a production workflow-owned run."""

        current = self.validate_create(asset_id, expected_m1_version_id)
        previous = None
        try:
            previous = self.repository.get_current_m2(asset_id).artifact_id
        except Exception as exc:
            from app.experience_asset.persistence import AssetNotFoundError

            if not isinstance(exc, AssetNotFoundError):
                raise
        artifact = self._derive(
            current,
            run_id=run_id,
            semantic_roles=semantic_roles,
        )
        self._append_transition(
            current,
            artifact,
            previous,
            "M2_CREATE",
            "Create M2 map.",
            derived_by_run_id=run_id,
        )
        return self._workspace(artifact)

    def get(self, asset_id: UUID) -> M2WorkspaceV1:
        artifact = self.repository.get_current_m2(asset_id)
        return self._workspace(artifact)

    def edit(self, asset_id: UUID, request: M2EditRequestV1) -> M2WorkspaceV1:
        current = self.repository.get_current_m2(asset_id)
        if current.artifact_id != request.expected_artifact_id:
            raise StorageConflictError("current M2 changed; reload before saving")
        if current.state is MilestoneState.INVALIDATED:
            raise M2ContractError("regenerate invalidated M2 before editing")
        canonical = self._assert_current_dependencies(asset_id, current)
        edits = {edit.moment_id: edit for edit in request.moments}
        known_ids = {moment.moment_id for moment in current.moments}
        if set(edits) != known_ids:
            raise M2ContractError("moment edits must contain each current moment exactly once")
        now = datetime.now(UTC)
        moments = []
        for moment in current.moments:
            edit = edits[moment.moment_id]
            title_changed = edit.title != moment.title
            if edit.criticality_status is not None:
                criticality_status = edit.criticality_status
            elif title_changed:
                criticality_status = "AGENT_PROPOSED"
            else:
                criticality_status = moment.criticality_status
            moments.append(
                moment.model_copy(
                    update={
                        "title": edit.title,
                        "criticality_status": criticality_status,
                        "criticality_confirmed_at": (
                            now
                            if edit.criticality_status == "USER_CONFIRMED"
                            else (
                                moment.criticality_confirmed_at
                                if criticality_status == "USER_CONFIRMED"
                                else None
                            )
                        ),
                    }
                )
            )
        next_artifact = current.model_copy(
            update={
                "artifact_id": uuid4(),
                "moments": moments,
                "state": self._draft_state(moments),
                "updated_at": now,
            }
        )
        self._append_transition(
            canonical, next_artifact, current.artifact_id, "M2_EDIT", "Edit M2 titles."
        )
        return self._workspace(next_artifact)

    def confirm(self, asset_id: UUID, request: M2ConfirmRequestV1) -> M2WorkspaceV1:
        current = self.repository.get_current_m2(asset_id)
        if current.artifact_id != request.expected_artifact_id:
            raise StorageConflictError("current M2 changed; reload before confirming")
        if current.state is MilestoneState.INVALIDATED:
            raise M2ContractError("invalidated M2 cannot be confirmed")
        canonical = self._assert_current_dependencies(asset_id, current)
        has_gaps = any(moment.temporal_status != "KNOWN" for moment in current.moments)
        if any(moment.criticality_status == "AGENT_PROPOSED" for moment in current.moments):
            raise M2ContractError("confirm each proposed critical moment or mark it unresolved")
        has_gaps = has_gaps or any(
            moment.criticality_status == "UNRESOLVED" for moment in current.moments
        )
        if has_gaps and not request.complete_with_gaps:
            raise M2ContractError("missing or conflicting time requires complete_with_gaps=true")
        next_artifact = current.model_copy(
            update={
                "artifact_id": uuid4(),
                "state": MilestoneState.COMPLETE_WITH_GAPS
                if has_gaps
                else MilestoneState.CONFIRMED,
                "updated_at": datetime.now(UTC),
            }
        )
        self._append_transition(
            canonical, next_artifact, current.artifact_id, "M2_CONFIRM", "Confirm M2 map."
        )
        return self._workspace(next_artifact)

    def _assert_current_dependencies(
        self, asset_id: UUID, artifact: CriticalMomentMapV1
    ) -> ExperienceAssetV1:
        canonical = self.repository.get_current(asset_id)
        base = self.repository.get_version(artifact.base_m1_version_id)
        if self._changed_dependencies(base, canonical, artifact) or self._changed_questions(
            base, canonical, artifact
        ):
            raise StorageConflictError("M1 dependencies changed; regenerate M2")
        return canonical

    def _append_transition(
        self,
        current: ExperienceAssetV1,
        artifact: CriticalMomentMapV1,
        expected_artifact_id: UUID | None,
        change_kind: str,
        change_reason: str,
        derived_by_run_id: UUID | None = None,
    ) -> ExperienceAssetV1:
        now = max(datetime.now(UTC), artifact.updated_at)
        canonical = project_m2(
            current,
            artifact,
            version_id=uuid4(),
            now=now,
            change_kind=change_kind,
            change_reason=change_reason,
            derived_by_run_id=derived_by_run_id,
        )
        m3_successor = None
        try:
            ledger = self.repository.get_current_m3(current.asset_id)
        except Exception as exc:
            from app.experience_asset.persistence import AssetNotFoundError

            if not isinstance(exc, AssetNotFoundError):
                raise
        else:
            from app.experience_asset.application.m3.invalidation import (
                successor_after_m2_transition,
            )
            from app.experience_asset.application.m3.projection import rebase_m3_projection

            old_m2 = self.repository.get_m2_artifact(expected_artifact_id)
            m3_successor = successor_after_m2_transition(
                ledger,
                old_m2=old_m2,
                new_m2=artifact,
                new_canonical_version_id=canonical.version_id,
                changed_at=canonical.updated_at,
            )
            canonical = rebase_m3_projection(canonical, m3_successor)
        self.repository.append_canonical_and_m2(
            canonical,
            artifact,
            expected_current_version_id=current.version_id,
            expected_current_artifact_id=expected_artifact_id,
            m3_successor=m3_successor,
        )
        return canonical

    def _derive(
        self,
        asset: ExperienceAssetV1,
        *,
        run_id: UUID,
        semantic_roles: dict[UUID, frozenset[M2SemanticRole]],
    ) -> CriticalMomentMapV1:
        now = datetime.now(UTC)
        statements = [
            s for s in asset.statements if s.confirmation.value not in {"CORRECTED", "REJECTED"}
        ]
        statement_ids = {statement.statement_id for statement in statements}
        if set(semantic_roles) != statement_ids:
            raise M2ContractError(
                "semantic role proposal must cover every usable M1 statement exactly once"
            )
        moments = []
        conflict_ids = {
            statement_id
            for question in asset.unresolved_questions
            if question.state in {QuestionState.OPEN, QuestionState.DEFERRED}
            and question.priority_inputs.get("missing_field") == "duration_conflict"
            for statement_id in question.affected_statement_ids
        }
        for order, statement in enumerate(statements):
            match = _TIME.search(statement.text)
            roles = semantic_roles[statement.statement_id]
            cue = "CUE" in roles
            change = "CHANGE" in roles
            surprise = "SURPRISE" in roles
            common = dict(
                moment_id=uuid4(),
                display_order=order,
                title=statement.text[:120],
                description=statement.text,
                criticality_status="AGENT_PROPOSED",
                criticality_reason=_criticality_reason(
                    cue=cue,
                    change=change,
                    surprise=surprise,
                ),
                criticality_confirmed_at=None,
                source_statement_ids=[statement.statement_id],
                cue_statement_ids=[statement.statement_id] if cue else [],
                change_statement_ids=[statement.statement_id] if change else [],
                surprise_statement_ids=[statement.statement_id] if surprise else [],
            )
            if statement.statement_id in conflict_ids:
                moments.append(
                    ConflictingTimeMomentV1(
                        **{**common, "source_statement_ids": sorted(conflict_ids, key=str)},
                        temporal_status="CONFLICTING",
                        time_label=None,
                        conflict_statement_ids=sorted(conflict_ids, key=str),
                        unresolved_reason=(
                            "The source gives incompatible same-day and extended-duration timing."
                        ),
                    )
                )
            elif match:
                moments.append(
                    KnownTimeMomentV1(
                        **common,
                        temporal_status="KNOWN",
                        time_label=match.group(0),
                        conflict_statement_ids=[],
                        unresolved_reason=None,
                    )
                )
            else:
                moments.append(
                    MissingTimeMomentV1(
                        **common,
                        temporal_status="MISSING",
                        time_label=None,
                        conflict_statement_ids=[],
                        unresolved_reason="The source does not state when this happened.",
                    )
                )
        if not moments:
            raise M2ContractError("accepted M1 has no usable statements")
        return CriticalMomentMapV1(
            artifact_id=uuid4(),
            asset_id=asset.asset_id,
            base_m1_version_id=asset.version_id,
            generated_by_run_id=run_id,
            state=self._draft_state(moments),
            order_basis="NARRATIVE_SEQUENCE",
            moments=moments,
            dependency_statement_ids=[s.statement_id for s in statements],
            unresolved_question_ids=[],
            created_at=now,
            updated_at=now,
            invalidated_by_m1_version_id=None,
            invalidation_reason=None,
        )

    @staticmethod
    def _draft_state(moments: list) -> MilestoneState:
        return (
            MilestoneState.NEEDS_INPUT
            if any(m.temporal_status != "KNOWN" for m in moments)
            else MilestoneState.REVIEW_READY
        )

    @staticmethod
    def _changed_dependencies(
        base: ExperienceAssetV1, current: ExperienceAssetV1, artifact: CriticalMomentMapV1
    ) -> set[UUID]:
        base_by_id = {s.statement_id: s for s in base.statements}
        current_by_id = {s.statement_id: s for s in current.statements}
        return {
            statement_id
            for statement_id in artifact.dependency_statement_ids
            if statement_id not in current_by_id
            or statement_id not in base_by_id
            or current_by_id[statement_id] != base_by_id[statement_id]
        }

    @staticmethod
    def _changed_questions(
        base: ExperienceAssetV1, current: ExperienceAssetV1, artifact: CriticalMomentMapV1
    ) -> bool:
        dependencies = set(artifact.dependency_statement_ids)
        base_questions = {
            question.question_id: question
            for question in base.unresolved_questions
            if dependencies.intersection(question.affected_statement_ids)
        }
        current_questions = {
            question.question_id: question
            for question in current.unresolved_questions
            if dependencies.intersection(question.affected_statement_ids)
        }
        return base_questions != current_questions

    def _workspace(self, artifact: CriticalMomentMapV1) -> M2WorkspaceV1:
        invalid = artifact.state is MilestoneState.INVALIDATED
        return M2WorkspaceV1(
            artifact=artifact,
            is_current=not invalid,
            history_artifact_ids=self.repository.list_m2_artifact_ids(artifact.asset_id),
            allowed_actions=["REGENERATE"] if invalid else ["EDIT", "CONFIRM", "REGENERATE"],
        )
