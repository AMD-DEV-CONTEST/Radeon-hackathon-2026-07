"""Deterministic M1 vertical-slice service over immutable canonical snapshots."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.application.m2.invalidation import invalidate_after_m1_correction
from app.experience_asset.application.m2.projection import project_m2
from app.experience_asset.domain.enums import (
    AssetLifecycle,
    ConfirmationState,
    EvidenceStrength,
    Milestone,
    MilestoneState,
    ProgressState,
    QuestionState,
    ReviewStatus,
    SourceAuthorship,
    SourceKind,
    StatementStatus,
    TerminalState,
)
from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.domain.m1 import (
    ExperienceBriefV1,
    M1BriefEditRequestV1,
    M1ConfirmRequestV1,
    M1IngestRequestV1,
    M1ProgressV1,
    M1QuestionActionV1,
    M1VersionActionRequestV1,
    M1WorkspaceV1,
)
from app.experience_asset.domain.models import (
    ExperienceAssetV1,
    MilestoneArtifact,
    ProgressEventV1,
    QuestionRecord,
    SourceReference,
    SourceSpan,
    Statement,
    TerminalResultV1,
    VersionLineage,
)
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)

_SENTENCE_BOUNDARY = re.compile(
    r"[。\uFF01\uFF1F]+[\u201d\u2019\u300d\u300f\u3011\u300b\u3009\uFF09]*"
    r"|[!?]+[\"'\u201d\u2019)\]}]*(?=\s|$|[A-Z\u3400-\u9fff])"
    r"|\.[\"'\u201d\u2019)\]}]*(?=\s|$|[A-Z\u3400-\u9fff])"
    r"|\n+"
)
_FIXTURE_METADATA = re.compile(r"^<!--.*-->$", re.DOTALL)
_CLAUSE_BOUNDARY = re.compile(r"[。\uFF01\uFF1F!?\uFF1B;]+|\n+")
_SAME_DAY = re.compile(
    r"(?:当天|当日|同一天)"
    r"|\b(?:the\s+)?same\s+day\b"
    r"|\bthat\s+day\b",
    re.IGNORECASE,
)
_TERMINAL_ACTION = re.compile(
    r"(?:退(?:掉|了|货|换)?|换(?:掉|了|货|成|为)?|更换)"
    r"|\b(?:return(?:ed|ing)?|swap(?:ped|ping)?|exchang(?:e|ed|ing))\b",
    re.IGNORECASE,
)
_EXTENDED_DURATION = re.compile(
    r"(?:"
    r"(?:约|大约|大概|差不多|将近|接近|连续|足足)?"
    r"(?:[2-9]\d*|[二两三四五六七八九十百几数]+)(?:个)?天"
    r"|(?:约|大约|大概|差不多|将近|接近|连续|足足)?"
    r"(?:\d+|[一二两三四五六七八九十百几数]+)(?:个)?(?:周|星期|月)"
    r"|(?:(?:about|around|roughly|nearly|almost)\s+)?"
    r"(?:(?:[2-9]\d*|two|three|four|five|six|seven|eight|nine|ten|"
    r"several|a\s+couple\s+of)\s+days?"
    r"|(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"several|a\s+couple\s+of)\s+(?:weeks?|months?))"
    r")",
    re.IGNORECASE,
)
_DURATION_ACTION = re.compile(
    r"(?:用|使用|试用|体验|试坐|坐了|测试|保留|持有|退|换|更换)"
    r"|\b(?:use(?:d|ing)?|try|tried|trying|test(?:ed|ing)?|keep|kept|"
    r"sit|sat|return(?:ed|ing)?|swap(?:ped|ping)?|exchang(?:e|ed|ing))\b",
    re.IGNORECASE,
)


def _split_source_sentences(text: str) -> list[str]:
    """Split common Chinese/English sentence boundaries without losing punctuation."""

    segments: list[str] = []
    cursor = 0
    for boundary in _SENTENCE_BOUNDARY.finditer(text):
        end = boundary.end()
        segment = text[cursor:end].strip()
        if segment:
            segments.append(segment)
        cursor = end
    tail = text[cursor:].strip()
    if tail:
        segments.append(tail)
    return segments


def _has_conflicting_duration(source_text: str) -> bool:
    """Surface a possible conflict only when short and extended claims coexist."""

    clauses = [
        clause.strip()
        for clause in _CLAUSE_BOUNDARY.split(source_text)
        if clause.strip()
    ]
    has_same_day_terminal = any(
        _SAME_DAY.search(clause) and _TERMINAL_ACTION.search(clause)
        for clause in clauses
    )
    has_extended_duration_action = any(
        _EXTENDED_DURATION.search(clause) and _DURATION_ACTION.search(clause)
        for clause in clauses
    )
    return has_same_day_terminal and has_extended_duration_action


class M1ContractError(ValueError):
    """The requested M1 transition would violate the frozen Issue contract."""


class M1ExperienceBriefService:
    """Own M1 state changes; every accepted change appends an immutable version."""

    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def ingest(self, request: M1IngestRequestV1) -> M1WorkspaceV1:
        now = datetime.now(UTC)
        asset = new_empty_asset(now=now)
        run_id = uuid4()
        source_id = uuid4()
        source = SourceReference(
            source_id=source_id,
            kind=request.source_kind,
            display_label=request.display_label,
            original_file_name=request.original_file_name,
            source_hash=hashlib.sha256(request.text.encode("utf-8")).hexdigest(),
            local_storage_ref=f"asset:{asset.asset_id}/source:{source_id}",
            source_url=request.source_url,
            adapted_provenance_notice=request.adapted_provenance_notice,
            span=SourceSpan(start=0, end=len(request.text)),
            ingested_at=now,
            authorship=request.authorship,
        )
        statements = self._source_statements(
            text=request.text,
            source_id=source_id,
            version_id=asset.version_id,
        )
        questions = self._initial_questions(
            run_id=run_id,
            version_id=asset.version_id,
            has_goal=bool(request.goal_hint.strip()),
            source_text=request.text,
            source_statements=statements,
        )
        brief = ExperienceBriefV1(
            context=(
                "\n".join(statement.text for statement in statements[:3])
                if statements
                else request.text.strip()
            ),
            goal=request.goal_hint.strip(),
            constraints=[],
            user_intent=request.goal_hint.strip(),
            source_boundary=(
                f"{request.display_label} · {request.source_kind.value} · "
                f"{len(request.text)} characters"
            ),
            source_ids=[source_id],
            statement_ids=[statement.statement_id for statement in statements],
            confirmed_statement_count=0,
            unresolved_question_count=len(questions),
        )
        artifact_state = (
            MilestoneState.NEEDS_INPUT if questions else MilestoneState.REVIEW_READY
        )
        artifact = self._artifact(
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            run_id=run_id,
            now=now,
            brief=brief,
            state=artifact_state,
            questions=questions,
        )
        payload = asset.model_dump(mode="python")
        payload.update(
            {
                "sources": [source],
                "context": brief.context,
                "goal": brief.goal,
                "constraints": brief.constraints,
                "user_intent": brief.user_intent,
                "statements": statements,
                "unresolved_questions": questions,
                "milestone_states": {
                    **asset.milestone_states,
                    Milestone.M1: artifact_state,
                },
                "milestone_artifacts": [artifact],
                "derivation_metadata": {
                    "m1_generator": "deterministic-current-source-v1",
                    "retrieval_scope": "CURRENT_SOURCE",
                    "source_content_trusted_as_policy": False,
                    "external_side_effects_allowed": False,
                    "model_inference_used": False,
                },
            }
        )
        created = ExperienceAssetV1.model_validate(payload)
        self.repository.create(created)
        terminal = (
            TerminalState.NEEDS_USER_INPUT if questions else TerminalState.SUCCEEDED
        )
        self._record_terminal_run(
            run_id=run_id,
            asset=created,
            command="E2-M1-INGEST",
            state=terminal,
            message=(
                "Experience Brief v0.1 saved; clarification is available."
                if questions
                else "Experience Brief v0.1 saved and ready for review."
            ),
        )
        return self._workspace(created, terminal_state=terminal, run_id=run_id)

    def get(self, asset_id: UUID) -> M1WorkspaceV1:
        asset = self.repository.get_current(asset_id)
        terminal = (
            TerminalState.PAUSED
            if asset.lifecycle is AssetLifecycle.PAUSED
            else self._terminal_for_asset(asset)
        )
        return self._workspace(asset, terminal_state=terminal, run_id=uuid4())

    def edit(self, asset_id: UUID, request: M1BriefEditRequestV1) -> M1WorkspaceV1:
        current = self._get_expected(asset_id, request.expected_version_id)
        self._require_active(current)
        brief = self._current_brief(current)
        edited = brief.model_copy(
            update={
                key: value
                for key, value in {
                    "context": request.context,
                    "goal": request.goal,
                    "constraints": request.constraints,
                    "user_intent": request.user_intent,
                }.items()
                if value is not None
            }
        )
        user_statement_texts: list[str] = []
        superseded_texts: list[str] = []
        for previous, changed in (
            (brief.context, request.context),
            (brief.goal, request.goal),
            (brief.user_intent, request.user_intent),
        ):
            if changed is not None and changed != previous:
                if previous.strip():
                    superseded_texts.append(previous.strip())
                if changed.strip():
                    user_statement_texts.append(changed.strip())
        if request.constraints is not None and request.constraints != brief.constraints:
            previous_constraints = {
                item.strip() for item in brief.constraints if item.strip()
            }
            changed_constraints = {
                item.strip() for item in request.constraints if item.strip()
            }
            superseded_texts.extend(
                sorted(previous_constraints - changed_constraints)
            )
            user_statement_texts.extend(sorted(changed_constraints - previous_constraints))
        return self._append_brief_version(
            current=current,
            brief=edited,
            change_kind="USER_EDIT",
            change_reason=request.change_reason,
            user_statement_texts=list(dict.fromkeys(user_statement_texts)),
            superseded_texts=list(dict.fromkeys(superseded_texts)),
        )

    def act_on_question(
        self,
        asset_id: UUID,
        question_id: UUID,
        request: M1QuestionActionV1,
    ) -> M1WorkspaceV1:
        current = self._get_expected(asset_id, request.expected_version_id)
        self._require_active(current)
        question = next(
            (
                candidate
                for candidate in current.unresolved_questions
                if candidate.question_id == question_id
            ),
            None,
        )
        if question is None:
            raise AssetNotFoundError(f"question: {question_id}")
        if question.state not in {QuestionState.OPEN, QuestionState.DEFERRED}:
            raise M1ContractError("question is already resolved")

        now = datetime.now(UTC)
        run_id = uuid4()
        version_id = uuid4()
        answer_source: SourceReference | None = None
        answer_statement: Statement | None = None
        if request.action == "ANSWER":
            answer_source_id = uuid4()
            answer_statement_id = uuid4()
            answer_text = request.answer or ""
            answer_source = SourceReference(
                source_id=answer_source_id,
                kind=SourceKind.CONVERSATION,
                display_label=f"Answer to question {question_id}",
                source_hash=hashlib.sha256(answer_text.encode("utf-8")).hexdigest(),
                local_storage_ref=(
                    f"asset:{current.asset_id}/question:{question_id}/answer"
                ),
                span=SourceSpan(start=0, end=len(answer_text)),
                ingested_at=now,
                authorship=SourceAuthorship.USER_AUTHORED,
            )
            answer_statement = Statement(
                statement_id=answer_statement_id,
                text=answer_text,
                status=StatementStatus.USER_JUDGMENT,
                source_refs=[answer_source_id],
                confirmation=ConfirmationState.CONFIRMED,
                evidence_strength=EvidenceStrength.SELF_REPORTED,
                created_in_version=version_id,
                last_changed_in_version=version_id,
            )
            next_state = QuestionState.ANSWERED
        elif request.action == "SKIP":
            answer_source_id = None
            answer_statement_id = None
            next_state = QuestionState.SKIPPED
        else:
            answer_source_id = None
            answer_statement_id = None
            next_state = QuestionState.DEFERRED

        updated_questions = [
            candidate.model_copy(
                update={
                    "state": next_state,
                    "answer_source_id": answer_source_id,
                    "answer_statement_id": answer_statement_id,
                    "resolved_by_run_id": (
                        run_id if next_state is not QuestionState.DEFERRED else None
                    ),
                    "resolved_in_version_id": (
                        version_id if next_state is not QuestionState.DEFERRED else None
                    ),
                }
            )
            if candidate.question_id == question_id
            else candidate
            for candidate in current.unresolved_questions
        ]
        open_questions = self._actionable_questions(updated_questions)
        brief = self._current_brief(current).model_copy(
            update={
                "statement_ids": [
                    *self._current_brief(current).statement_ids,
                    *(
                        [answer_statement.statement_id]
                        if answer_statement is not None
                        else []
                    ),
                ],
                "confirmed_statement_count": (
                    self._current_brief(current).confirmed_statement_count
                    + (1 if answer_statement is not None else 0)
                ),
                "unresolved_question_count": len(open_questions),
            }
        )
        state = (
            MilestoneState.NEEDS_INPUT
            if open_questions
            else MilestoneState.REVIEW_READY
        )
        artifact = self._artifact(
            asset_id=current.asset_id,
            version_id=version_id,
            run_id=run_id,
            now=now,
            brief=brief,
            state=state,
            questions=open_questions,
        )
        updated = self._version_payload(
            current=current,
            version_id=version_id,
            now=now,
            run_id=run_id,
            change_kind=f"QUESTION_{request.action}",
            change_reason=f"{request.action.title()} M1 clarification question.",
            brief=brief,
            artifact=artifact,
            questions=updated_questions,
            extra_sources=[answer_source] if answer_source else [],
            extra_statements=[answer_statement] if answer_statement else [],
            lifecycle=current.lifecycle,
            milestone_state=state,
            current_milestone=Milestone.M1,
        )
        try:
            current_m2 = self.repository.get_current_m2(current.asset_id)
        except AssetNotFoundError:
            current_m2 = None
        invalidated_m2 = (
            invalidate_after_m1_correction(
                current_m2,
                corrected_statement_ids=set(question.affected_statement_ids),
                new_m1_version_id=version_id,
                changed_at=max(now, current_m2.updated_at),
            )
            if current_m2 is not None
            and next_state is not QuestionState.DEFERRED
            and question.affected_statement_ids
            else current_m2
        )
        if invalidated_m2 is not None and invalidated_m2 is not current_m2:
            invalidated_m2 = invalidated_m2.model_copy(update={"artifact_id": uuid4()})
            updated = project_m2(
                updated,
                invalidated_m2,
                version_id=version_id,
                now=now,
                change_kind=f"QUESTION_{request.action}",
                change_reason=f"{request.action.title()} M1 clarification question.",
                parent_version_id=current.version_id,
                derived_by_run_id=run_id,
            )
            m3_successor, updated = self._successor_for_m1_m2_transition(
                updated, current_m2, invalidated_m2
            )
            self.repository.append_canonical_and_m2(
                updated,
                invalidated_m2,
                expected_current_version_id=current.version_id,
                expected_current_artifact_id=current_m2.artifact_id,
                m3_successor=m3_successor,
            )
        else:
            self.repository.append(updated, expected_current_version_id=current.version_id)
        terminal = (
            TerminalState.NEEDS_USER_INPUT
            if open_questions
            else TerminalState.SUCCEEDED
        )
        self._record_terminal_run(
            run_id=run_id,
            asset=updated,
            command=f"E2-M1-QUESTION-{request.action}",
            state=terminal,
            message="Question action saved to a new immutable version.",
        )
        return self._workspace(updated, terminal_state=terminal, run_id=run_id)

    def pause(
        self,
        asset_id: UUID,
        request: M1VersionActionRequestV1,
    ) -> M1WorkspaceV1:
        current = self._get_expected(asset_id, request.expected_version_id)
        if current.lifecycle is AssetLifecycle.PAUSED:
            raise M1ContractError("asset is already paused")
        return self._append_lifecycle(
            current=current,
            lifecycle=AssetLifecycle.PAUSED,
            command="E2-M1-PAUSE",
            state=TerminalState.PAUSED,
        )

    def resume(
        self,
        asset_id: UUID,
        request: M1VersionActionRequestV1,
    ) -> M1WorkspaceV1:
        current = self._get_expected(asset_id, request.expected_version_id)
        if current.lifecycle is not AssetLifecycle.PAUSED:
            raise M1ContractError("asset is not paused")
        return self._append_lifecycle(
            current=current,
            lifecycle=AssetLifecycle.ACTIVE,
            command="E2-M1-RESUME",
            state=self._terminal_for_asset(current),
        )

    def confirm(
        self,
        asset_id: UUID,
        request: M1ConfirmRequestV1,
    ) -> M1WorkspaceV1:
        current = self._get_expected(asset_id, request.expected_version_id)
        self._require_active(current)
        open_questions = self._actionable_questions(current.unresolved_questions)
        if open_questions and not request.complete_with_gaps:
            raise M1ContractError(
                "open or deferred questions require complete_with_gaps=true"
            )
        brief = self._current_brief(current)
        state = (
            MilestoneState.COMPLETE_WITH_GAPS
            if open_questions
            else MilestoneState.CONFIRMED
        )
        now = datetime.now(UTC)
        run_id = uuid4()
        version_id = uuid4()
        artifact = self._artifact(
            asset_id=current.asset_id,
            version_id=version_id,
            run_id=run_id,
            now=now,
            brief=brief,
            state=state,
            questions=open_questions,
            review_status=(
                ReviewStatus.ACCEPTED_WITH_GAPS
                if open_questions
                else ReviewStatus.ACCEPTED
            ),
        )
        updated = self._version_payload(
            current=current,
            version_id=version_id,
            now=now,
            run_id=run_id,
            change_kind="M1_CONFIRM",
            change_reason="Confirm M1 Experience Brief.",
            brief=brief,
            artifact=artifact,
            questions=current.unresolved_questions,
            lifecycle=AssetLifecycle.ACTIVE,
            milestone_state=state,
            current_milestone=Milestone.M2,
        )
        self.repository.append(updated, expected_current_version_id=current.version_id)
        self._record_terminal_run(
            run_id=run_id,
            asset=updated,
            command="E2-M1-CONFIRM",
            state=TerminalState.SUCCEEDED,
            message="M1 Experience Brief confirmed and saved.",
        )
        return self._workspace(
            updated,
            terminal_state=TerminalState.SUCCEEDED,
            run_id=run_id,
        )

    def _append_brief_version(
        self,
        *,
        current: ExperienceAssetV1,
        brief: ExperienceBriefV1,
        change_kind: str,
        change_reason: str,
        user_statement_texts: list[str],
        superseded_texts: list[str],
    ) -> M1WorkspaceV1:
        now = datetime.now(UTC)
        run_id = uuid4()
        version_id = uuid4()
        superseded = set(superseded_texts)
        superseded_statement_ids = {
            statement.statement_id
            for statement in current.statements
            if statement.status is StatementStatus.USER_JUDGMENT
            and statement.confirmation is ConfirmationState.CONFIRMED
            and statement.text in superseded
        }
        base_statements = [
            statement.model_copy(
                update={
                    "confirmation": ConfirmationState.CORRECTED,
                    "last_changed_in_version": version_id,
                }
            )
            if statement.statement_id in superseded_statement_ids
            else statement
            for statement in current.statements
        ]
        retained_confirmed_texts = {
            statement.text
            for statement in base_statements
            if statement.status is StatementStatus.USER_JUDGMENT
            and statement.confirmation is ConfirmationState.CONFIRMED
        }
        user_statements = [
            Statement(
                statement_id=uuid4(),
                text=text,
                status=StatementStatus.USER_JUDGMENT,
                confirmation=ConfirmationState.CONFIRMED,
                evidence_strength=EvidenceStrength.SELF_REPORTED,
                created_in_version=version_id,
                last_changed_in_version=version_id,
            )
            for text in user_statement_texts
            if text not in retained_confirmed_texts
        ]
        brief = brief.model_copy(
            update={
                "statement_ids": [
                    *brief.statement_ids,
                    *(statement.statement_id for statement in user_statements),
                ],
                "confirmed_statement_count": (
                    max(
                        0,
                        brief.confirmed_statement_count
                        - len(superseded_statement_ids),
                    )
                    + len(user_statements)
                ),
            }
        )
        questions = self._actionable_questions(current.unresolved_questions)
        state = (
            MilestoneState.NEEDS_INPUT
            if questions
            else MilestoneState.REVIEW_READY
        )
        terminal_state = (
            TerminalState.NEEDS_USER_INPUT
            if questions
            else TerminalState.SUCCEEDED
        )
        artifact = self._artifact(
            asset_id=current.asset_id,
            version_id=version_id,
            run_id=run_id,
            now=now,
            brief=brief.model_copy(
                update={"unresolved_question_count": len(questions)}
            ),
            state=state,
            questions=questions,
        )
        updated = self._version_payload(
            current=current,
            version_id=version_id,
            now=now,
            run_id=run_id,
            change_kind=change_kind,
            change_reason=change_reason,
            brief=ExperienceBriefV1.model_validate(artifact.payload),
            artifact=artifact,
            questions=current.unresolved_questions,
            lifecycle=current.lifecycle,
            milestone_state=state,
            base_statements=base_statements,
            extra_statements=user_statements,
            current_milestone=Milestone.M1,
        )
        try:
            current_m2 = self.repository.get_current_m2(current.asset_id)
        except AssetNotFoundError:
            current_m2 = None
        invalidated_m2 = (
            invalidate_after_m1_correction(
                current_m2,
                corrected_statement_ids=superseded_statement_ids,
                new_m1_version_id=version_id,
                changed_at=max(now, current_m2.updated_at),
            )
            if current_m2 is not None and superseded_statement_ids
            else current_m2
        )
        if invalidated_m2 is not None and invalidated_m2 is not current_m2:
            invalidated_m2 = invalidated_m2.model_copy(update={"artifact_id": uuid4()})
            updated = project_m2(
                updated,
                invalidated_m2,
                version_id=version_id,
                now=now,
                change_kind=change_kind,
                change_reason=change_reason,
                parent_version_id=current.version_id,
                derived_by_run_id=run_id,
            )
            m3_successor, updated = self._successor_for_m1_m2_transition(
                updated, current_m2, invalidated_m2
            )
            self.repository.append_canonical_and_m2(
                updated,
                invalidated_m2,
                expected_current_version_id=current.version_id,
                expected_current_artifact_id=current_m2.artifact_id,
                m3_successor=m3_successor,
            )
        else:
            self.repository.append(updated, expected_current_version_id=current.version_id)
        self._record_terminal_run(
            run_id=run_id,
            asset=updated,
            command="E2-M1-AUTOSAVE",
            state=terminal_state,
            message="Experience Brief edit autosaved.",
        )
        return self._workspace(updated, terminal_state=terminal_state, run_id=run_id)

    def _successor_for_m1_m2_transition(self, canonical, old_m2, new_m2):
        """Rebase an existing M3 in the same transaction as an M1-owned M2 replacement."""
        try:
            ledger = self.repository.get_current_m3(canonical.asset_id)
        except AssetNotFoundError:
            return None, canonical
        from app.experience_asset.application.m3.invalidation import successor_after_m2_transition
        from app.experience_asset.application.m3.projection import rebase_m3_projection

        successor = successor_after_m2_transition(
            ledger,
            old_m2=old_m2,
            new_m2=new_m2,
            new_canonical_version_id=canonical.version_id,
            changed_at=canonical.updated_at,
        )
        return successor, rebase_m3_projection(canonical, successor)

    def _append_lifecycle(
        self,
        *,
        current: ExperienceAssetV1,
        lifecycle: AssetLifecycle,
        command: str,
        state: TerminalState,
    ) -> M1WorkspaceV1:
        now = datetime.now(UTC)
        run_id = uuid4()
        version_id = uuid4()
        payload = current.model_dump(mode="python")
        payload.update(
            {
                "version_id": version_id,
                "updated_at": now,
                "lifecycle": lifecycle,
                "route_decisions": [
                    decision.model_copy(
                        update={"canonical_version_id": version_id}
                    )
                    for decision in current.route_decisions
                ],
                "lineage": VersionLineage(
                    version_id=version_id,
                    parent_version_id=current.version_id,
                    change_kind=command,
                    change_reason=(
                        "Pause M1 work and preserve durable state."
                        if lifecycle is AssetLifecycle.PAUSED
                        else "Resume M1 work from the last durable version."
                    ),
                    created_at=now,
                    derived_by_run_id=run_id,
                ),
            }
        )
        updated = ExperienceAssetV1.model_validate(payload)
        self.repository.append(updated, expected_current_version_id=current.version_id)
        self._record_terminal_run(
            run_id=run_id,
            asset=updated,
            command=command,
            state=state,
            message=(
                "M1 work paused after a durable save."
                if state is TerminalState.PAUSED
                else "M1 work resumed from the last durable version."
            ),
        )
        return self._workspace(updated, terminal_state=state, run_id=run_id)

    @staticmethod
    def _source_statements(
        *,
        text: str,
        source_id: UUID,
        version_id: UUID,
    ) -> list[Statement]:
        raw_segments = [
            segment for segment in _split_source_sentences(text) if segment
        ]
        segments = [
            segment
            for segment in raw_segments
            if not _FIXTURE_METADATA.match(segment)
            and not segment.startswith(
                "This is an adapted, paraphrased, and anonymized public-research fixture"
            )
            and segment
            not in {"not first-party testimony.", "first-party testimony."}
        ][:80]
        if not segments:
            segments = [text.strip()]
        return [
            Statement(
                statement_id=uuid4(),
                text=segment,
                status=StatementStatus.SOURCE_FACT,
                source_refs=[source_id],
                confirmation=ConfirmationState.UNCONFIRMED,
                evidence_strength=EvidenceStrength.SELF_REPORTED,
                created_in_version=version_id,
                last_changed_in_version=version_id,
            )
            for segment in segments
        ]

    @staticmethod
    def _initial_questions(
        *,
        run_id: UUID,
        version_id: UUID,
        has_goal: bool,
        source_text: str,
        source_statements: list[Statement],
    ) -> list[QuestionRecord]:
        definitions = []
        if _has_conflicting_duration(source_text):
            affected_statement_ids = [
                statement.statement_id
                for statement in source_statements
                if (
                    _SAME_DAY.search(statement.text)
                    and _TERMINAL_ACTION.search(statement.text)
                )
                or (
                    _EXTENDED_DURATION.search(statement.text)
                    and _DURATION_ACTION.search(statement.text)
                )
            ]
            definitions.append(
                (
                    "资料中的使用时长似乎冲突\uFF1A一处表示当天就退换\uFF0C"
                    "另一处表示持续使用了多日或数周。实际时间线是哪一种\uFF1F",
                    "时间边界存在冲突时\uFF0C系统不能替你选择一个版本或补造顺序。",
                    "duration_conflict",
                    affected_statement_ids,
                )
            )
        if not has_goal:
            definitions.append(
                (
                    "你希望把这段经历保留下来解决什么问题或用于什么场景\uFF1F",
                    "用途会决定 Experience Brief 的目标边界\uFF0C但不会改变原始事实。",
                    "goal",
                    [],
                )
            )
        definitions.extend(
            [
                (
                    "这段经历从哪里开始、到哪里结束\uFF1F",
                    "明确起止边界可以避免把无关事件混入当前资产。",
                    "boundary",
                    [],
                ),
                (
                    "当时有哪些必须保留的条件或限制\uFF1F",
                    "限制会影响这段经验是否能在其他场景复用。",
                    "constraint",
                    [],
                ),
            ]
        )
        return [
            QuestionRecord(
                question_id=uuid4(),
                question=question,
                why_it_matters=reason,
                milestone=Milestone.M1,
                affected_statement_ids=affected_statement_ids,
                priority_inputs={"missing_field": missing_field},
                created_by_run_id=run_id,
                created_in_version_id=version_id,
            )
            for question, reason, missing_field, affected_statement_ids in definitions[:3]
        ]

    @staticmethod
    def _artifact(
        *,
        asset_id: UUID,
        version_id: UUID,
        run_id: UUID,
        now: datetime,
        brief: ExperienceBriefV1,
        state: MilestoneState,
        questions: list[QuestionRecord],
        review_status: ReviewStatus = ReviewStatus.NOT_REVIEWED,
    ) -> MilestoneArtifact:
        return MilestoneArtifact(
            artifact_id=uuid4(),
            artifact_type="ExperienceBriefV1",
            asset_id=asset_id,
            version_id=version_id,
            milestone=Milestone.M1,
            state=state,
            statement_ids=brief.statement_ids,
            unresolved_question_ids=[
                question.question_id for question in questions
            ],
            generated_by_run_id=run_id,
            user_review_status=review_status,
            created_at=now,
            updated_at=now,
            payload=brief.model_dump(mode="json"),
        )

    def _version_payload(
        self,
        *,
        current: ExperienceAssetV1,
        version_id: UUID,
        now: datetime,
        run_id: UUID,
        change_kind: str,
        change_reason: str,
        brief: ExperienceBriefV1,
        artifact: MilestoneArtifact,
        questions: list[QuestionRecord],
        lifecycle: AssetLifecycle,
        milestone_state: MilestoneState,
        extra_sources: list[SourceReference] | None = None,
        extra_statements: list[Statement] | None = None,
        base_statements: list[Statement] | None = None,
        current_milestone: Milestone | None = None,
    ) -> ExperienceAssetV1:
        payload = current.model_dump(mode="python")
        payload.update(
            {
                "version_id": version_id,
                "updated_at": now,
                "lifecycle": lifecycle,
                "current_milestone": current_milestone or current.current_milestone,
                "context": brief.context,
                "goal": brief.goal,
                "constraints": brief.constraints,
                "user_intent": brief.user_intent,
                "sources": [*current.sources, *(extra_sources or [])],
                "statements": [
                    *(base_statements if base_statements is not None else current.statements),
                    *(extra_statements or []),
                ],
                "unresolved_questions": questions,
                "milestone_states": {
                    **current.milestone_states,
                    Milestone.M1: milestone_state,
                },
                "milestone_artifacts": [
                    artifact_item
                    for artifact_item in current.milestone_artifacts
                    if artifact_item.milestone is not Milestone.M1
                ]
                + [artifact],
                "route_decisions": [
                    decision.model_copy(
                        update={"canonical_version_id": version_id}
                    )
                    for decision in current.route_decisions
                ],
                "lineage": VersionLineage(
                    version_id=version_id,
                    parent_version_id=current.version_id,
                    change_kind=change_kind,
                    change_reason=change_reason,
                    created_at=now,
                    derived_by_run_id=run_id,
                ),
            }
        )
        return ExperienceAssetV1.model_validate(payload)

    @staticmethod
    def _actionable_questions(
        questions: list[QuestionRecord],
    ) -> list[QuestionRecord]:
        return [
            question
            for question in questions
            if question.state in {QuestionState.OPEN, QuestionState.DEFERRED}
        ][:3]

    @staticmethod
    def _current_brief(asset: ExperienceAssetV1) -> ExperienceBriefV1:
        artifact = next(
            (
                candidate
                for candidate in reversed(asset.milestone_artifacts)
                if candidate.milestone is Milestone.M1
                and candidate.artifact_type == "ExperienceBriefV1"
            ),
            None,
        )
        if artifact is None:
            raise M1ContractError("asset has no M1 Experience Brief")
        return ExperienceBriefV1.model_validate(artifact.payload)

    def _get_expected(
        self,
        asset_id: UUID,
        expected_version_id: UUID,
    ) -> ExperienceAssetV1:
        current = self.repository.get_current(asset_id)
        if current.version_id != expected_version_id:
            raise StorageConflictError("current version changed; reload before saving")
        return current

    @staticmethod
    def _require_active(asset: ExperienceAssetV1) -> None:
        if asset.lifecycle is AssetLifecycle.PAUSED:
            raise M1ContractError("resume the asset before modifying M1")

    @staticmethod
    def _terminal_for_asset(asset: ExperienceAssetV1) -> TerminalState:
        if asset.milestone_states[Milestone.M1] in {
            MilestoneState.CONFIRMED,
            MilestoneState.COMPLETE_WITH_GAPS,
            MilestoneState.REVIEW_READY,
        }:
            return TerminalState.SUCCEEDED
        return TerminalState.NEEDS_USER_INPUT

    def _workspace(
        self,
        asset: ExperienceAssetV1,
        *,
        terminal_state: TerminalState,
        run_id: UUID,
    ) -> M1WorkspaceV1:
        brief = self._current_brief(asset)
        artifact = next(
            candidate
            for candidate in reversed(asset.milestone_artifacts)
            if candidate.milestone is Milestone.M1
        )
        questions = self._actionable_questions(asset.unresolved_questions)
        progress_state = (
            ProgressState.TERMINAL
            if terminal_state
            in {
                TerminalState.SUCCEEDED,
                TerminalState.PAUSED,
            }
            else ProgressState.WAITING_FOR_USER
        )
        progress_event = ProgressEventV1(
            event_id=uuid4(),
            run_id=run_id,
            asset_id=asset.asset_id,
            version_id=asset.version_id,
            sequence=len(self.repository.list_version_ids(asset.asset_id)),
            stage="M1_EXPERIENCE_BRIEF",
            state=progress_state,
            internal_completed_units=(
                4
                if artifact.state
                in {MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS}
                else 3
            ),
            internal_total_units=4,
            message=(
                "M1 已确认并保存。"
                if artifact.state
                in {MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS}
                else f"Experience Brief 已保存\uFF1B{len(questions)} 个问题仍可处理。"
            ),
            occurred_at=asset.updated_at,
            terminal_state=terminal_state if progress_state is ProgressState.TERMINAL else None,
        )
        latest_agent_run = self.repository.get_latest_asset_run_checkpoint(
            asset.asset_id
        )
        if (
            latest_agent_run is not None
            and latest_agent_run.base_version_id != asset.version_id
        ):
            latest_agent_run = None
        actions = ["EDIT", "PAUSE", "RUN_AGENT_CURRENT"]
        if questions:
            actions.extend(["ANSWER", "SKIP", "DEFER"])
        if asset.lifecycle is AssetLifecycle.PAUSED:
            actions = ["RESUME"]
        elif artifact.state not in {
            MilestoneState.CONFIRMED,
            MilestoneState.COMPLETE_WITH_GAPS,
        }:
            actions.append("CONFIRM")
        return M1WorkspaceV1(
            asset=asset,
            brief=brief,
            questions=questions,
            progress=M1ProgressV1(
                artifact_state=artifact.state.value,
                confirmed_statement_count=brief.confirmed_statement_count,
                unresolved_question_count=len(questions),
                saved_version_id=asset.version_id,
                last_saved_at=asset.updated_at,
            ),
            progress_event=progress_event,
            terminal_state=terminal_state,
            latest_agent_run=latest_agent_run,
            allowed_actions=actions,
        )

    def _record_terminal_run(
        self,
        *,
        run_id: UUID,
        asset: ExperienceAssetV1,
        command: str,
        state: TerminalState,
        message: str,
    ) -> None:
        started = datetime.now(UTC)
        self.repository.start_run(
            run_id=run_id,
            asset_id=asset.asset_id,
            command=command,
            model_id="deterministic-current-source-v1",
            model_config_hash="0" * 64,
            code_commit=None,
            started_at=started,
        )
        self.repository.finish_run(
            TerminalResultV1(
                run_id=run_id,
                state=state,
                last_durable_version_id=asset.version_id,
                retryable=state
                in {
                    TerminalState.NEEDS_USER_INPUT,
                    TerminalState.PAUSED,
                },
                safe_user_message=message,
                elapsed_ms=0,
                model_call_count=0,
                recovery_action=(
                    "Resume from the saved version or provide clarification."
                    if state
                    in {
                        TerminalState.NEEDS_USER_INPUT,
                        TerminalState.PAUSED,
                    }
                    else "No recovery required."
                ),
                finished_at=datetime.now(UTC),
            )
        )
