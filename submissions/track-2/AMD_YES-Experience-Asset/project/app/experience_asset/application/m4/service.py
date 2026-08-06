"""M4 application service; SQLite owns all canonical truth."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import (
    Milestone,
    MilestoneState,
    ProgressState,
    StatementStatus,
    TerminalState,
)
from app.experience_asset.domain.m4 import (
    REQUIRED_INSIGHT_ROLES,
    InsightBoundaryMapV1,
    InsightEntryV1,
    InsightStatementV1,
    M4EditRequestV1,
    M4EvidenceStatementV1,
    M4FailureV1,
    M4ProgressV1,
    M4RunStatusV1,
    M4WorkspaceV1,
)
from app.experience_asset.inference.models import M4MapProposal
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)

from .invalidation import successor_after_m3_transition
from .projection import project_m4

ACCEPTED_M3_STATES = frozenset({MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS})

FAILURE_CODE_BY_TERMINAL = {
    TerminalState.INVALID_MODEL_OUTPUT: "INVALID_MODEL_OUTPUT",
    TerminalState.MODEL_UNAVAILABLE: "MODEL_UNAVAILABLE",
    TerminalState.TIMED_OUT: "MODEL_TIMED_OUT",
    TerminalState.STORAGE_ERROR: "STORAGE_ERROR",
    TerminalState.POLICY_BLOCKED: "PERMISSION_DENIED",
    TerminalState.NEEDS_USER_INPUT: "UPSTREAM_STALE",
}


class M4ContractError(ValueError):
    pass


class M4MapService:
    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    # ------------------------------------------------------------------
    # Preconditions
    # ------------------------------------------------------------------

    def validate_create(
        self, asset_id: UUID, m3_id: UUID, version_id: UUID, *, regenerate: bool = False
    ):
        self.reconcile_upstream(asset_id)
        m3, current = (
            self.repository.get_current_m3(asset_id),
            self.repository.get_current(asset_id),
        )
        if (m3.artifact_id, current.version_id) != (m3_id, version_id):
            raise StorageConflictError("current accepted M3/canonical pair changed")
        if m3.state not in ACCEPTED_M3_STATES:
            raise M4ContractError("M4 requires an accepted M3 ledger")
        projection = next(
            (a for a in current.milestone_artifacts if a.milestone is Milestone.M3), None
        )
        if projection is None or projection.payload.get("m3_artifact_id") != str(m3_id):
            raise M4ContractError("canonical M3 projection does not reference accepted M3")
        try:
            self.repository.get_current_m4(asset_id)
        except AssetNotFoundError:
            pass
        else:
            if not regenerate:
                raise M4ContractError(
                    "M4 already exists; use explicit regeneration if invalidated"
                )
        return m3, current

    def reconcile_upstream(self, asset_id: UUID) -> None:
        """Bring the stored map into line with the current ledger before any M4 read or write.

        Invalidation is pulled at the M4 seam rather than pushed from the M1-M3
        services. Pushing would mean editing those services and the M3 append
        signature, which the integration contract assigns to no Wave-1 ticket,
        and a shape that needs three other owners to change is not a shape this
        ticket can land. Pulling costs a write on the first read after a
        correction; that is the price of keeping the trigger inside one owner.

        M1 and M2 corrections reach here through the ledger, because E4 already
        rebases or invalidates M3 in the same transaction that records them. So
        one comparison against the current M3 covers all three upstream sources.
        """
        try:
            artifact = self.repository.get_current_m4(asset_id)
        except AssetNotFoundError:
            return
        # An already-invalidated map has said everything it can say. Recomputing
        # would append a canonical version on every read while the user's only
        # available move stays the same: regenerate.
        if artifact.state is MilestoneState.INVALIDATED:
            return
        current_m3 = self.repository.get_current_m3(asset_id)
        if current_m3.artifact_id == artifact.base_m3_artifact_id:
            return
        old_m3 = self.repository.get_m3_artifact(artifact.base_m3_artifact_id)
        canonical = self.repository.get_current(asset_id)
        now = datetime.now(UTC)
        version_id = uuid4()
        successor = successor_after_m3_transition(
            artifact,
            old_m3=old_m3,
            new_m3=current_m3,
            new_canonical_version_id=version_id,
            changed_at=now,
        )
        invalidated = successor.state is MilestoneState.INVALIDATED
        snapshot = project_m4(
            canonical,
            successor,
            version_id=version_id,
            now=now,
            change_kind="M4_INVALIDATE" if invalidated else "M4_REBASE",
            change_reason=(
                "Upstream correction retired the evidence this map rests on"
                if invalidated
                else "Rebase the map onto the corrected ledger it still matches"
            ),
        )
        self.repository.append_canonical_and_m4_successor(
            snapshot,
            successor,
            expected_current_version_id=canonical.version_id,
            expected_current_artifact_id=artifact.artifact_id,
            expected_m3_artifact_id=current_m3.artifact_id,
        )

    def validate_regenerate(self, asset_id: UUID, expected_artifact_id: UUID):
        current = self.repository.get_current_m4(asset_id)
        if current.artifact_id != expected_artifact_id:
            raise StorageConflictError("current invalidated M4 changed")
        if current.state is not MilestoneState.INVALIDATED:
            raise M4ContractError("regenerate requires the current invalidated M4 artifact")
        return current

    def readable_identities(self, asset_id: UUID) -> tuple[dict[UUID, set[UUID]], set[UUID]]:
        """Return the decision-scoped statement identities an M4 proposal may cite.

        Everything readable comes from this asset's accepted ledger and the
        canonical statements that ledger already cites. Widening the set to all
        canonical statements would let a lesson rest on material no decision
        stands behind, and widening it across assets is what ticket 05 exists to
        gate — doing it here would anchor an experience the user is still
        clarifying, invisibly.
        """
        m3 = self.repository.get_current_m3(asset_id)
        canonical_ids = {
            statement.statement_id for statement in self.repository.get_current(asset_id).statements
        }
        by_decision: dict[UUID, set[UUID]] = {}
        for entry in m3.entries:
            readable: set[UUID] = set()
            for statement in entry.statements:
                readable.add(statement.statement_id)
                readable.update(statement.source_statement_ids)
                readable.update(statement.derived_from_statement_ids)
            by_decision[entry.decision_id] = readable & canonical_ids
        return by_decision, canonical_ids

    def validate_proposal(
        self, asset_id: UUID, proposal: M4MapProposal, *, previous=None
    ) -> None:
        """Validate every model-owned reference and the required role shape.

        Structural repair inside the graph never reaches persistence without
        passing here: a half-accepted proposal would leave the artifact in a
        state no contract describes, and the frozen validators would then reject
        the very artifact the user is looking at.
        """
        by_decision, _ = self.readable_identities(asset_id)
        prior_ids = [entry.prior_insight_id for entry in proposal.entries]
        if previous is None and any(prior_ids):
            raise M4ContractError("new M4 proposals must not identify a prior insight")
        if previous is not None:
            affected = set(previous.affected_insight_ids)
            named = [item for item in prior_ids if item is not None]
            if len(named) != len(prior_ids):
                raise M4ContractError("regeneration must name a prior insight for every entry")
            if len(named) != len(affected) or set(named) != affected:
                raise M4ContractError(
                    "regeneration must replace every affected insight exactly once"
                )
            if len(named) != len(set(named)):
                raise M4ContractError("regeneration duplicates a prior insight")
            if set(named) & set(previous.reusable_insight_ids):
                raise M4ContractError("regeneration cannot touch reusable insights")
        for entry in proposal.entries:
            if len(entry.source_decision_ids) != len(set(entry.source_decision_ids)):
                raise M4ContractError("M4 entry source decision IDs must be unique")
            if not set(entry.source_decision_ids).issubset(by_decision):
                raise M4ContractError("M4 proposal references unknown decision")
            roles = [statement.role for statement in entry.statements]
            if set(roles) != set(REQUIRED_INSIGHT_ROLES) or roles.count("LESSON") != 1:
                raise M4ContractError("M4 proposal must include every required role")
            readable = {
                statement_id
                for decision_id in entry.source_decision_ids
                for statement_id in by_decision[decision_id]
            }
            for statement in entry.statements:
                for label, values in (
                    ("source statement", statement.source_statement_ids),
                    ("source decision", statement.source_decision_ids),
                ):
                    if len(values) != len(set(values)):
                        raise M4ContractError(f"M4 {label} IDs must be unique")
                if not set(statement.source_decision_ids).issubset(set(entry.source_decision_ids)):
                    raise M4ContractError("M4 statement references a decision outside its entry")
                if not set(statement.source_statement_ids).issubset(readable):
                    raise M4ContractError(
                        "M4 evidence must belong to the statement's declared source decisions"
                    )
                grounded = bool(statement.source_statement_ids or statement.source_decision_ids)
                if (
                    statement.role in {"LESSON", "SUPPORT"}
                    and not statement.source_statement_ids
                ):
                    raise M4ContractError(
                        "M4 lesson and support must cite a canonical source statement"
                    )
                if statement.gap_reason is not None and grounded:
                    raise M4ContractError("a declared gap cannot also cite canonical sources")
                if statement.gap_reason is None and not grounded:
                    raise M4ContractError(
                        "an ungrounded M4 statement must declare a gap reason; otherwise it "
                        "renders with the same authority as a grounded one"
                    )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_for_run(
        self,
        asset_id: UUID,
        *,
        m3_id: UUID,
        version_id: UUID,
        run_id: UUID,
        proposal: M4MapProposal,
        expected_invalidated_artifact_id: UUID | None = None,
    ) -> InsightBoundaryMapV1:
        previous = (
            self.validate_regenerate(asset_id, expected_invalidated_artifact_id)
            if expected_invalidated_artifact_id is not None
            else None
        )
        self.validate_create(
            asset_id,
            m3_id,
            version_id,
            regenerate=expected_invalidated_artifact_id is not None,
        )
        self.validate_proposal(asset_id, proposal, previous=previous)
        current = self.repository.get_current(asset_id)
        entries: list[InsightEntryV1] = []
        for proposed_entry in proposal.entries:
            statements = [
                InsightStatementV1(
                    statement_id=uuid4(),
                    role=item.role,
                    text=item.text,
                    status=StatementStatus.UNRESOLVED
                    if item.gap_reason is not None
                    else StatementStatus.AGENT_INFERENCE,
                    source_statement_ids=item.source_statement_ids,
                    source_decision_ids=item.source_decision_ids,
                    is_visible_gap=item.gap_reason is not None,
                    gap_reason=item.gap_reason,
                )
                for item in proposed_entry.statements
            ]
            entries.append(
                InsightEntryV1(
                    insight_id=proposed_entry.prior_insight_id or uuid4(),
                    title=proposed_entry.title,
                    source_decision_ids=proposed_entry.source_decision_ids,
                    statements=statements,
                )
            )
        if previous is not None:
            reusable = [
                entry
                for entry in previous.entries
                if entry.insight_id in previous.reusable_insight_ids
            ]
            entries = [*reusable, *entries]
        now = datetime.now(UTC)
        artifact = InsightBoundaryMapV1(
            artifact_id=uuid4(),
            asset_id=asset_id,
            base_m3_artifact_id=m3_id,
            base_canonical_version_id=version_id,
            generated_by_run_id=run_id,
            state=self._state_for(entries),
            entries=entries,
            dependency_decision_ids=sorted(
                {item for entry in entries for item in entry.source_decision_ids}, key=str
            ),
            dependency_statement_ids=sorted(
                {
                    item
                    for entry in entries
                    for statement in entry.statements
                    for item in statement.source_statement_ids
                },
                key=str,
            ),
            unresolved_question_ids=[],
            created_at=now,
            updated_at=now,
        )
        self._append(
            current,
            artifact,
            previous.artifact_id if previous else None,
            "M4_REGENERATE" if previous else "M4_CREATE",
            "Regenerate affected M4 insights" if previous else "Create M4 insight map",
            graph_run_id=run_id,
        )
        return artifact

    def edit(self, asset_id: UUID, request: M4EditRequestV1) -> M4WorkspaceV1:
        self.reconcile_upstream(asset_id)
        current = self.repository.get_current_m4(asset_id)
        if current.artifact_id != request.expected_artifact_id:
            raise StorageConflictError("current M4 changed")
        if current.state is MilestoneState.INVALIDATED:
            raise M4ContractError("invalidated M4 cannot be edited; regenerate it")
        canonical = self.repository.get_current(asset_id)
        edits = {item.statement_id: item for item in request.edits}
        known_ids = {s.statement_id for e in current.entries for s in e.statements}
        unknown_ids = set(edits) - known_ids
        if unknown_ids:
            raise M4ContractError("statement edit references unknown M4 statement")
        by_decision, _ = self.readable_identities(asset_id)
        now = datetime.now(UTC)
        entries = []
        for entry in current.entries:
            readable = {
                statement_id
                for decision_id in entry.source_decision_ids
                for statement_id in by_decision.get(decision_id, set())
            }
            statements = []
            for statement in entry.statements:
                edit = edits.get(statement.statement_id)
                if edit is None:
                    statements.append(statement)
                    continue
                statements.append(self._apply_edit(statement, edit, entry, readable))
            entries.append(entry.model_copy(update={"statements": statements}))
        artifact = InsightBoundaryMapV1.model_validate(
            {
                **current.model_dump(mode="python"),
                "artifact_id": uuid4(),
                "base_canonical_version_id": canonical.version_id,
                "entries": entries,
                "state": self._state_for(entries),
                "dependency_statement_ids": sorted(
                    {
                        item
                        for entry in entries
                        for statement in entry.statements
                        for item in statement.source_statement_ids
                    },
                    key=str,
                ),
                "updated_at": now,
            }
        )
        if artifact.entries == current.entries:
            raise M4ContractError("M4 edit has no semantic effect")
        self._append(canonical, artifact, current.artifact_id, "M4_EDIT", "Edit M4 insight map")
        return self.get(asset_id)

    def _apply_edit(self, statement, edit, entry, readable: set[UUID]) -> InsightStatementV1:
        update: dict[str, object] = {}
        if edit.text is not None:
            update["text"] = edit.text
        if edit.source_statement_ids is not None:
            if not set(edit.source_statement_ids).issubset(readable):
                raise M4ContractError(
                    "edited evidence must belong to the insight's source decisions"
                )
            update["source_statement_ids"] = edit.source_statement_ids
        if edit.source_decision_ids is not None:
            if not set(edit.source_decision_ids).issubset(set(entry.source_decision_ids)):
                raise M4ContractError("edited statement references a decision outside its entry")
            update["source_decision_ids"] = edit.source_decision_ids
        if edit.is_visible_gap is not None:
            update["is_visible_gap"] = edit.is_visible_gap
            if edit.is_visible_gap:
                # Marking a gap retires the citations with it; keeping them
                # would leave a statement that both cites evidence and claims
                # none exists, which the frozen validator rejects and a reader
                # could not interpret either way.
                update.setdefault("source_statement_ids", [])
                update.setdefault("source_decision_ids", [])
                update["source_statement_ids"] = []
                update["source_decision_ids"] = []
                update["status"] = StatementStatus.UNRESOLVED
            else:
                update["gap_reason"] = None
        if edit.gap_reason is not None:
            update["gap_reason"] = edit.gap_reason
        if edit.status is not None:
            update["status"] = edit.status
        candidate = statement.model_copy(update=update)
        if candidate.is_visible_gap and candidate.gap_reason is None:
            raise M4ContractError("marking a gap requires an explicit gap_reason")
        # Re-validate through the frozen contract so an edit cannot reach a
        # shape generation is forbidden to produce.
        return InsightStatementV1.model_validate(candidate.model_dump(mode="python"))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, asset_id: UUID) -> M4WorkspaceV1:
        self.reconcile_upstream(asset_id)
        canonical = self.repository.get_current(asset_id)
        try:
            artifact = self.repository.get_current_m4(asset_id)
        except AssetNotFoundError:
            artifact = None
        return M4WorkspaceV1(
            asset_id=asset_id,
            canonical_version_id=canonical.version_id,
            canonical_content_hash=self.repository.get_version_content_hash(canonical.version_id),
            map=artifact,
            evidence_statements=self._evidence(canonical, artifact),
            run_status=self._latest_run_status(asset_id),
        )

    def run_status(self, asset_id: UUID, run_id: UUID) -> M4RunStatusV1:
        outcome = self.repository.get_m4_run_outcome(run_id)
        if outcome is None or str(outcome.get("asset_id")) != str(asset_id):
            raise AssetNotFoundError(f"M4 run {run_id}")
        return self._run_status(outcome)

    def _evidence(self, canonical, artifact) -> list[M4EvidenceStatementV1]:
        if artifact is None:
            return []
        cited = set(artifact.dependency_statement_ids)
        source_labels = {source.source_id: source.display_label for source in canonical.sources}
        return [
            M4EvidenceStatementV1(
                statement_id=statement.statement_id,
                text=statement.text,
                status=statement.status,
                source_refs=[
                    source_labels[source_id]
                    for source_id in statement.source_refs
                    if source_id in source_labels
                ],
            )
            for statement in canonical.statements
            if statement.statement_id in cited
        ]

    def _latest_run_status(self, asset_id: UUID) -> M4RunStatusV1 | None:
        latest = self.repository.get_latest_m4_run(asset_id)
        if latest is None:
            return None
        return self._run_status({**latest, "asset_id": str(asset_id)})

    def _run_status(self, outcome: dict) -> M4RunStatusV1:
        run_id = UUID(str(outcome["run_id"]))
        asset_id = UUID(str(outcome["asset_id"]))
        terminal_value = outcome.get("terminal_state")
        occurred_at = outcome.get("finished_at") or outcome.get("started_at")
        if terminal_value is None:
            return M4RunStatusV1(
                run_id=run_id,
                asset_id=asset_id,
                state=ProgressState.RUNNING,
                progress=M4ProgressV1(
                    run_id=run_id,
                    asset_id=asset_id,
                    sequence=0,
                    stage="LOAD_CONTEXT",
                    state=ProgressState.RUNNING,
                    message="M4 generation is running.",
                    occurred_at=occurred_at,
                ),
            )
        terminal = TerminalState(str(terminal_value))
        if terminal is TerminalState.SUCCEEDED:
            return M4RunStatusV1(
                run_id=run_id,
                asset_id=asset_id,
                state=ProgressState.TERMINAL,
                progress=M4ProgressV1(
                    run_id=run_id,
                    asset_id=asset_id,
                    sequence=0,
                    stage="TERMINAL",
                    state=ProgressState.TERMINAL,
                    message=str(outcome.get("safe_user_message") or "M4 map saved."),
                    occurred_at=occurred_at,
                ),
            )
        return M4RunStatusV1(
            run_id=run_id,
            asset_id=asset_id,
            state=ProgressState.TERMINAL,
            failure=M4FailureV1(
                run_id=run_id,
                asset_id=asset_id,
                failure_code=FAILURE_CODE_BY_TERMINAL.get(terminal, "INVALID_MODEL_OUTPUT"),
                terminal_state=terminal,
                retryable=bool(outcome.get("retryable")),
                safe_user_message=str(outcome.get("safe_user_message") or "M4 stopped safely."),
                occurred_at=occurred_at,
            ),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _state_for(entries) -> MilestoneState:
        has_gap = any(
            statement.is_visible_gap for entry in entries for statement in entry.statements
        )
        return MilestoneState.NEEDS_INPUT if has_gap else MilestoneState.REVIEW_READY

    def _append(self, current, artifact, expected, kind, reason, *, graph_run_id=None):
        canonical = project_m4(
            current,
            artifact,
            version_id=uuid4(),
            now=artifact.updated_at,
            change_kind=kind,
            change_reason=reason,
        )
        self.repository.append_canonical_and_m4(
            canonical,
            artifact,
            expected_current_version_id=current.version_id,
            expected_current_artifact_id=expected,
            expected_m3_artifact_id=artifact.base_m3_artifact_id,
            graph_run_id=graph_run_id,
        )
