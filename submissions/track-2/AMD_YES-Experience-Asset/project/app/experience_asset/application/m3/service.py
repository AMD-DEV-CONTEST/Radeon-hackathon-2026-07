"""M3 application service; SQLite owns all canonical truth."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import (
    ConfirmationState,
    EvidenceStrength,
    Milestone,
    MilestoneState,
    StatementStatus,
    TerminalState,
)
from app.experience_asset.domain.m3 import (
    DecisionEvidenceLedgerV1,
    DecisionLedgerEntryV1,
    LedgerStatementV1,
    M3ConfirmRequestV1,
    M3EditRequestV1,
    M3EvidenceMomentV1,
    M3EvidenceStatementV1,
    M3FailureV1,
    M3ProgressV1,
    M3WorkspaceV1,
    public_m3_failure_code,
)
from app.experience_asset.inference.models import M3LedgerProposal
from app.experience_asset.persistence import (
    SQLiteAssetRepository,
    StorageConflictError,
)

from .projection import project_m3


class M3ContractError(ValueError):
    pass


class M3LedgerService:
    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def validate_create(self, asset_id: UUID, m2_id: UUID, version_id: UUID, *, regenerate=False):
        m2, current = (
            self.repository.get_current_m2(asset_id),
            self.repository.get_current(asset_id),
        )
        if (m2.artifact_id, current.version_id) != (m2_id, version_id):
            raise StorageConflictError("current accepted M2/canonical pair changed")
        if m2.state not in {MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS}:
            raise M3ContractError("M3 requires accepted M2")
        projection = next(
            (a for a in current.milestone_artifacts if a.milestone is Milestone.M2), None
        )
        if projection is None or projection.payload.get("m2_artifact_id") != str(m2_id):
            raise M3ContractError("canonical M2 projection does not reference accepted M2")
        try:
            self.repository.get_current_m3(asset_id)
        except Exception as exc:
            from app.experience_asset.persistence import AssetNotFoundError

            if not isinstance(exc, AssetNotFoundError):
                raise
        else:
            if not regenerate:
                raise M3ContractError("M3 already exists; use explicit regeneration if invalidated")
        return m2, current

    def validate_regenerate(self, asset_id: UUID, expected_artifact_id: UUID):
        current = self.repository.get_current_m3(asset_id)
        if current.artifact_id != expected_artifact_id:
            raise StorageConflictError("current invalidated M3 changed")
        if current.state is not MilestoneState.INVALIDATED:
            raise M3ContractError("regenerate requires the current invalidated M3 artifact")
        return current

    def validate_proposal(
        self, asset_id: UUID, proposal: M3LedgerProposal, *, previous=None
    ) -> None:
        """Validate all model-owned references and required role shape before persistence."""
        m2 = self.repository.get_current_m2(asset_id)
        current = self.repository.get_current(asset_id)
        moment_ids = {moment.moment_id for moment in m2.moments}
        moment_statement_ids = {
            moment.moment_id: set(moment.source_statement_ids) for moment in m2.moments
        }
        statement_ids = {statement.statement_id for statement in current.statements}
        prior_ids = [entry.prior_decision_id for entry in proposal.entries]
        if previous is None and any(prior_ids):
            raise M3ContractError("new M3 proposals must not identify a prior decision")
        if previous is not None:
            affected = set(previous.affected_entry_ids)
            if len(prior_ids) != len(affected) or set(prior_ids) != affected:
                raise M3ContractError(
                    "regeneration must replace every affected decision exactly once"
                )
            if len(prior_ids) != len(set(prior_ids)):
                raise M3ContractError("regeneration duplicates a prior decision")
            if set(prior_ids) & set(previous.reusable_entry_ids):
                raise M3ContractError("regeneration cannot touch reusable decisions")
        for entry in proposal.entries:
            if len(entry.source_moment_ids) != len(set(entry.source_moment_ids)):
                raise M3ContractError("M3 entry source moment IDs must be unique")
            if not set(entry.source_moment_ids).issubset(moment_ids):
                raise M3ContractError("M3 proposal references unknown moment")
            roles = [statement.role for statement in entry.statements]
            if (
                set(roles) != {"ALTERNATIVE", "REASON", "DECISION", "ACTION", "OBSERVED_RESULT"}
                or roles.count("DECISION") != 1
            ):
                raise M3ContractError("M3 proposal must include every required role")
            for statement in entry.statements:
                for label, values in (
                    ("source moment", statement.source_moment_ids),
                    ("source statement", statement.source_statement_ids),
                    ("derived statement", statement.derived_from_statement_ids),
                ):
                    if len(values) != len(set(values)):
                        raise M3ContractError(f"M3 {label} IDs must be unique")
                if not set(statement.source_moment_ids).issubset(set(entry.source_moment_ids)):
                    raise M3ContractError("M3 statement references a moment outside its entry")
                refs = set(statement.source_statement_ids) | set(
                    statement.derived_from_statement_ids
                )
                if not refs.issubset(statement_ids):
                    raise M3ContractError("M3 proposal references unknown statement")
                linked_statement_ids = {
                    statement_id
                    for moment_id in statement.source_moment_ids
                    for statement_id in moment_statement_ids[moment_id]
                }
                if not refs.issubset(linked_statement_ids):
                    raise M3ContractError(
                        "M3 evidence must belong to the statement's declared source moments"
                    )
                if statement.unresolved_reason is None and not refs:
                    raise M3ContractError("supported M3 statement requires evidence")

    def create_for_run(
        self,
        asset_id: UUID,
        *,
        m2_id: UUID,
        version_id: UUID,
        run_id: UUID,
        proposal: M3LedgerProposal,
        expected_invalidated_artifact_id: UUID | None = None,
    ) -> DecisionEvidenceLedgerV1:
        previous = (
            self.validate_regenerate(asset_id, expected_invalidated_artifact_id)
            if expected_invalidated_artifact_id is not None
            else None
        )
        m2, current = self.validate_create(
            asset_id, m2_id, version_id, regenerate=expected_invalidated_artifact_id is not None
        )
        self.validate_proposal(asset_id, proposal, previous=previous)
        moment_ids = {moment.moment_id for moment in m2.moments}
        source_ids = {s.statement_id for s in current.statements}
        entries = []
        for proposed_entry in proposal.entries:
            if not set(proposed_entry.source_moment_ids).issubset(moment_ids):
                raise M3ContractError("M3 proposal references unknown moment")
            statements = []
            for item in proposed_entry.statements:
                refs = set(item.source_statement_ids) | set(item.derived_from_statement_ids)
                if not refs.issubset(source_ids):
                    raise M3ContractError("M3 proposal references unknown statement")
                unresolved = item.unresolved_reason is not None or not refs
                statements.append(
                    LedgerStatementV1(
                        statement_id=uuid4(),
                        role=item.role,
                        text=item.text,
                        status=StatementStatus.UNRESOLVED
                        if unresolved
                        else StatementStatus.AGENT_INFERENCE,
                        evidence_disposition="UNRESOLVED" if unresolved else "SUPPORTED",
                        evidence_strength=EvidenceStrength.NONE
                        if unresolved
                        else EvidenceStrength.INDIRECT,
                        confirmation=ConfirmationState.UNCONFIRMED,
                        confirmed_at=None,
                        source_moment_ids=item.source_moment_ids,
                        source_statement_ids=item.source_statement_ids,
                        derived_from_statement_ids=item.derived_from_statement_ids,
                        unresolved_reason=item.unresolved_reason
                        or ("No source evidence was supplied." if unresolved else None),
                    )
                )
            entries.append(
                DecisionLedgerEntryV1(
                    decision_id=proposed_entry.prior_decision_id or uuid4(),
                    title=proposed_entry.title,
                    source_moment_ids=proposed_entry.source_moment_ids,
                    statements=statements,
                )
            )
        now = datetime.now(UTC)
        if previous is not None:
            reusable = [
                entry
                for entry in previous.entries
                if entry.decision_id in previous.reusable_entry_ids
            ]
            entries = [*reusable, *entries]
        artifact = DecisionEvidenceLedgerV1(
            artifact_id=uuid4(),
            asset_id=asset_id,
            base_m2_artifact_id=m2_id,
            base_canonical_version_id=version_id,
            generated_by_run_id=run_id,
            state=MilestoneState.NEEDS_INPUT
            if any(s.status is StatementStatus.UNRESOLVED for e in entries for s in e.statements)
            else MilestoneState.REVIEW_READY,
            entries=entries,
            dependency_moment_ids=sorted(
                {x for e in entries for x in e.source_moment_ids}, key=str
            ),
            dependency_statement_ids=sorted(
                {
                    x
                    for e in entries
                    for s in e.statements
                    for x in (s.source_statement_ids + s.derived_from_statement_ids)
                },
                key=str,
            ),
            unresolved_question_ids=[],
            created_at=now,
            updated_at=now,
            invalidated_by_m2_artifact_id=None,
            invalidated_by_canonical_version_id=None,
            invalidation_reason=None,
        )
        self._append(
            current,
            artifact,
            previous.artifact_id if previous else None,
            "M3_REGENERATE" if previous else "M3_CREATE",
            "Regenerate affected M3 entries" if previous else "Create M3 ledger",
            graph_run_id=run_id,
        )
        return artifact

    def get(self, asset_id: UUID) -> M3WorkspaceV1:
        artifact = self.repository.get_current_m3(asset_id)
        return self._workspace(artifact)

    def edit(self, asset_id: UUID, request: M3EditRequestV1) -> M3WorkspaceV1:
        current = self.repository.get_current_m3(asset_id)
        if current.artifact_id != request.expected_artifact_id:
            raise StorageConflictError("current M3 changed")
        if current.state is MilestoneState.INVALIDATED:
            raise M3ContractError("invalidated M3 cannot be edited; regenerate it")
        canonical = self.repository.get_current(asset_id)
        edits = {item.statement_id: item for item in request.statements}
        known_ids = {s.statement_id for e in current.entries for s in e.statements}
        unknown_ids = set(edits) - known_ids
        if unknown_ids:
            raise M3ContractError("statement edit references unknown M3 statement")
        now = datetime.now(UTC)
        entries = []
        for entry in current.entries:
            statements = []
            for statement in entry.statements:
                edit = edits.get(statement.statement_id)
                if edit is None:
                    statements.append(statement)
                    continue
                changed = edit.text != statement.text
                action = edit.user_action
                if changed and action is None:
                    raise M3ContractError("changed text requires CONFIRM or MARK_UNRESOLVED")
                update = {"text": edit.text}
                if action == "CONFIRM":
                    update.update(
                        status=StatementStatus.USER_JUDGMENT,
                        evidence_disposition="SUPPORTED",
                        evidence_strength=EvidenceStrength.SELF_REPORTED,
                        confirmation=ConfirmationState.CONFIRMED,
                        confirmed_at=now,
                        unresolved_reason=None,
                    )
                elif action == "MARK_UNRESOLVED":
                    update.update(
                        status=StatementStatus.UNRESOLVED,
                        evidence_disposition="UNRESOLVED",
                        evidence_strength=EvidenceStrength.NONE,
                        confirmation=ConfirmationState.UNCONFIRMED,
                        confirmed_at=None,
                        unresolved_reason=edit.unresolved_reason,
                    )
                statements.append(statement.model_copy(update=update))
            entries.append(entry.model_copy(update={"statements": statements}))
        artifact = DecisionEvidenceLedgerV1.model_validate(
            {
                **current.model_dump(mode="python"),
                "artifact_id": uuid4(),
                "base_canonical_version_id": canonical.version_id,
                "entries": entries,
                "state": MilestoneState.NEEDS_INPUT
                if any(
                    s.status is StatementStatus.UNRESOLVED for e in entries for s in e.statements
                )
                else MilestoneState.REVIEW_READY,
                "updated_at": now,
            }
        )
        if artifact.entries == current.entries:
            raise M3ContractError("M3 edit has no semantic effect")
        self._append(canonical, artifact, current.artifact_id, "M3_EDIT", "Edit M3 ledger")
        return self.get(asset_id)

    def confirm(self, asset_id: UUID, request: M3ConfirmRequestV1) -> M3WorkspaceV1:
        current = self.repository.get_current_m3(asset_id)
        if current.artifact_id != request.expected_artifact_id:
            raise StorageConflictError("current M3 changed")
        if current.state is MilestoneState.INVALIDATED:
            raise M3ContractError("invalidated M3 cannot be confirmed; regenerate it")
        gaps = any(
            s.status is StatementStatus.UNRESOLVED or s.evidence_disposition == "CONFLICTING"
            for e in current.entries
            for s in e.statements
        )
        if gaps and not request.complete_with_gaps:
            raise M3ContractError("visible gaps require complete_with_gaps=true")
        if any(
            s.status is not StatementStatus.UNRESOLVED
            and s.confirmation is not ConfirmationState.CONFIRMED
            for e in current.entries
            for s in e.statements
        ):
            raise M3ContractError("confirm every supported statement explicitly")
        canonical = self.repository.get_current(asset_id)
        artifact = DecisionEvidenceLedgerV1.model_validate(
            {
                **current.model_dump(mode="python"),
                "artifact_id": uuid4(),
                "base_canonical_version_id": canonical.version_id,
                "state": MilestoneState.COMPLETE_WITH_GAPS if gaps else MilestoneState.CONFIRMED,
                "updated_at": datetime.now(UTC),
            }
        )
        self._append(
            canonical,
            artifact,
            current.artifact_id,
            "M3_CONFIRM",
            "Confirm M3 ledger",
        )
        return self.get(asset_id)

    def _append(self, current, artifact, expected, kind, reason, *, graph_run_id=None):
        canonical = project_m3(
            current,
            artifact,
            version_id=uuid4(),
            now=artifact.updated_at,
            change_kind=kind,
            change_reason=reason,
        )
        self.repository.append_canonical_and_m3(
            canonical,
            artifact,
            expected_current_version_id=current.version_id,
            expected_current_artifact_id=expected,
            expected_m2_artifact_id=artifact.base_m2_artifact_id,
            graph_run_id=graph_run_id,
        )

    def _workspace(self, artifact):
        invalid = artifact.state is MilestoneState.INVALIDATED
        source_m2 = self.repository.get_m2_artifact(artifact.base_m2_artifact_id)
        source_canonical = self.repository.get_version(
            artifact.base_canonical_version_id
        )
        dependency_moment_ids = set(artifact.dependency_moment_ids)
        dependency_statement_ids = set(artifact.dependency_statement_ids)
        source_labels = {
            source.source_id: source.display_label
            for source in source_canonical.sources
        }
        evidence_moments = [
            M3EvidenceMomentV1(
                moment_id=moment.moment_id,
                title=moment.title,
                description=moment.description,
            )
            for moment in source_m2.moments
            if moment.moment_id in dependency_moment_ids
        ]
        evidence_statements = [
            M3EvidenceStatementV1(
                statement_id=statement.statement_id,
                text=statement.text,
                source_labels=[
                    source_labels[source_id]
                    for source_id in statement.source_refs
                    if source_id in source_labels
                ],
            )
            for statement in source_canonical.statements
            if statement.statement_id in dependency_statement_ids
        ]
        latest = self.repository.get_latest_m3_run(artifact.asset_id)
        failure_applies = bool(
            latest
            and latest["terminal_state"] != "SUCCEEDED"
            and (
                not invalid
                or latest["expected_invalidated_m3_artifact_id"]
                == str(artifact.artifact_id)
            )
        )
        failed = latest if failure_applies else None
        if invalid and not failure_applies:
            terminal = TerminalState.NEEDS_USER_INPUT
        elif latest and latest["terminal_state"]:
            terminal = TerminalState(latest["terminal_state"])
        else:
            terminal = TerminalState.SUCCEEDED
        calls = int(latest["model_call_count"] or 0) if latest else 0
        repairs = int(latest["structured_repair_count"] or 0) if latest else 0
        replans = int(latest["replan_count"] or 0) if latest else 0
        message = (
            "M3 is invalidated; explicitly regenerate affected decisions."
            if invalid
            else str(latest["safe_user_message"] if latest else "M3 ledger saved.")
        )
        latest_failure = None
        if failed:
            codes = __import__("json").loads(str(failed["finding_codes_json"]))
            latest_failure = M3FailureV1(
                code=public_m3_failure_code(failed["terminal_state"], codes),
                terminal_state=failed["terminal_state"],
                retryable=bool(failed["retryable"]),
                safe_user_message=failed["safe_user_message"],
                recovery_action=failed["recovery_action"],
                finding_codes=codes or ["INTERNAL_ERROR"],
                occurred_at=failed["finished_at"],
            )
        return M3WorkspaceV1(
            artifact=artifact,
            is_current=not invalid,
            history_artifact_ids=self.repository.list_m3_artifact_ids(artifact.asset_id),
            evidence_moments=evidence_moments,
            evidence_statements=evidence_statements,
            progress=M3ProgressV1(
                stage="TERMINAL",
                state="TERMINAL",
                structured_repairs_used=repairs,
                replans_used=replans,
                model_calls_used=calls,
                last_durable_artifact_id=artifact.artifact_id,
                safe_message=message,
                occurred_at=artifact.updated_at,
                terminal_state=terminal,
            ),
            latest_failure=latest_failure,
            allowed_actions=["REGENERATE"] if invalid else ["EDIT", "CONFIRM"],
        )
