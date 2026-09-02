from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from creative_hub.quality import (
    CandidateVersion,
    EvaluatorBundle,
    GateExhaustionPolicy,
    GateOutcome,
    GateOutcomeKind,
    GatePolicySnapshot,
    HumanReviewMode,
    MachineJudgment,
    QualityError,
    QualityStage,
    RepairProposal,
    ResourceUsage,
)


# Workflow stage cursor:
#
#   ASSET -> KEYFRAME -> CLIP -> FINAL
#      |         |         |       |
#      +-- each gate may create immutable candidates/rework in place
#      +-- a sealed stage can never be reopened in the same WorkflowRun
#
# A gate result and its Selection CAS are one boundary. Late evaluations are
# retained as candidate history but cannot change the sealed pointer.


class SelectionSealer(Protocol):
    def seal(
        self,
        *,
        candidate: CandidateVersion,
        expected_selection_version: int,
        decision: str,
        reason: str,
    ) -> None: ...


class CertificationAuthority(Protocol):
    def is_certified(self, bundle: EvaluatorBundle) -> bool: ...


@dataclass
class MemorySelectionSealer:
    state_version: int = 0
    sealed_candidate_id: UUID | None = None
    decision: str | None = None

    def seal(
        self,
        *,
        candidate: CandidateVersion,
        expected_selection_version: int,
        decision: str,
        reason: str,
    ) -> None:
        del reason
        if self.sealed_candidate_id is not None:
            raise QualityError("selection is already sealed")
        if self.state_version != expected_selection_version:
            raise QualityError("selection CAS version changed")
        self.sealed_candidate_id = candidate.candidate_id
        self.decision = decision
        self.state_version += 1


@dataclass
class ForwardOnlyStageLedger:
    project_id: UUID
    workflow_run_id: UUID
    _sealed: list[QualityStage] = field(default_factory=list)

    @property
    def sealed(self) -> tuple[QualityStage, ...]:
        return tuple(self._sealed)

    def assert_current(self, stage: QualityStage) -> None:
        expected_ordinal = len(self._sealed)
        if stage.ordinal != expected_ordinal:
            if stage in self._sealed:
                raise QualityError(
                    "sealed upstream stage requires a new Workflow revision/run"
                )
            raise QualityError("quality stages must advance in strict order")

    def seal(self, stage: QualityStage) -> None:
        self.assert_current(stage)
        self._sealed.append(stage)


class GateEngine:
    """Deterministic current-stage QC, repair, and best-of-N policy engine."""

    def __init__(
        self,
        *,
        policy: GatePolicySnapshot,
        certifications: CertificationAuthority,
        selection_sealer: SelectionSealer,
    ) -> None:
        self.policy = policy
        self.certifications = certifications
        self.selection_sealer = selection_sealer
        self._candidates: list[CandidateVersion] = []
        self._actual_repair_usage = ResourceUsage()
        self._pending_repair: GateOutcome | None = None
        self._terminal: GateOutcome | None = None

    @property
    def candidates(self) -> tuple[CandidateVersion, ...]:
        return tuple(self._candidates)

    def restore_history(
        self,
        *,
        candidates: tuple[CandidateVersion, ...],
        outcomes: tuple[GateOutcome, ...],
    ) -> None:
        """Restore an append-only gate without replaying selection side effects."""

        if self._candidates or self._pending_repair or self._terminal:
            raise QualityError("quality gate history is already initialized")
        if len(candidates) != len(outcomes):
            raise QualityError(
                "persisted gate history requires one outcome per candidate"
            )
        try:
            for index, (candidate, outcome) in enumerate(
                zip(candidates, outcomes, strict=True)
            ):
                self.add_candidate(candidate)
                if (
                    outcome.stage != self.policy.stage
                    or outcome.gate_key != self.policy.gate_key
                ):
                    raise QualityError(
                        "persisted gate outcome does not belong to this gate"
                    )
                outcome_candidate = next(
                    (
                        item
                        for item in self._candidates
                        if item.candidate_id == outcome.candidate_id
                    ),
                    None,
                )
                if outcome_candidate is None:
                    raise QualityError(
                        "persisted gate outcome references an unknown candidate"
                    )
                if (
                    outcome.expected_selection_version
                    != outcome_candidate.evaluation.expected_selection_version
                ):
                    raise QualityError(
                        "persisted gate outcome selection version mismatch"
                    )
                is_last = index == len(outcomes) - 1
                if outcome.kind is GateOutcomeKind.REWORK_PLANNED:
                    proposal = outcome.repair_proposal
                    if (
                        proposal is None
                        or proposal.parent_candidate_id
                        != candidate.candidate_id
                        or outcome.candidate_id != candidate.candidate_id
                    ):
                        raise QualityError(
                            "persisted rework decision is not bound to "
                            "the latest candidate"
                        )
                    self._pending_repair = outcome
                    continue
                if not is_last:
                    raise QualityError(
                        "persisted terminal gate outcome must be the final event"
                    )
                self._terminal = outcome
        except Exception:
            self._candidates.clear()
            self._actual_repair_usage = ResourceUsage()
            self._pending_repair = None
            self._terminal = None
            raise

    def add_candidate(self, candidate: CandidateVersion) -> None:
        if self._terminal is not None:
            raise QualityError("sealed/terminal gate rejects late candidates")
        if (
            candidate.project_id != self.policy.project_id
            or candidate.workflow_run_id != self.policy.workflow_run_id
            or candidate.stage != self.policy.stage
            or candidate.gate_key != self.policy.gate_key
        ):
            raise QualityError("candidate does not belong to this gate")
        if candidate.evaluation.expected_selection_version < 0:
            raise QualityError("evaluation selection version is invalid")
        if candidate.ordinal != len(self._candidates) + 1:
            raise QualityError("candidate ordinals must be contiguous")
        if self._candidates and self._pending_repair is None:
            raise QualityError(
                "derived candidate requires an admitted same-stage repair"
            )
        if any(
            prior.candidate_id == candidate.candidate_id
            or prior.artifact.artifact_id == candidate.artifact.artifact_id
            for prior in self._candidates
        ):
            raise QualityError("candidate versions are immutable and unique")
        if (
            candidate.evaluation.evaluator.bundle_digest
            != self.policy.evaluator_bundle_digest
            or candidate.evaluation.evaluator.prompt_revision_id
            != self.policy.prompt_revision_id
            or candidate.evaluation.evaluator.rubric_revision_id
            != self.policy.rubric_revision_id
        ):
            raise QualityError("evaluation does not match gate policy snapshot")
        self._candidates.append(candidate)
        if candidate.ordinal > 1:
            # Actual usage is accounting truth even if it exceeded the
            # admission estimate. It closes future repair admission; it does
            # not erase an already produced immutable candidate.
            self._actual_repair_usage = self._actual_repair_usage.plus(
                candidate.generation_usage
            )
            self._pending_repair = None

    def _rank(self, candidate: CandidateVersion) -> tuple[float, float, str]:
        weights = self.policy.ranking_weights
        score = (
            candidate.evaluation.quality_score
            * float(weights.get("quality_score", 1.0))
            + candidate.evaluation.confidence
            * float(weights.get("confidence", 0.0))
        )
        return (
            score,
            candidate.evaluation.confidence,
            str(candidate.candidate_id),
        )

    def _is_certified(self, candidate: CandidateVersion) -> bool:
        return self.certifications.is_certified(candidate.evaluation.evaluator)

    def _seal(
        self,
        *,
        candidate: CandidateVersion,
        kind: GateOutcomeKind,
        reason: str,
    ) -> GateOutcome:
        expected = candidate.evaluation.expected_selection_version
        self.selection_sealer.seal(
            candidate=candidate,
            expected_selection_version=expected,
            decision=kind.value,
            reason=reason,
        )
        outcome = GateOutcome(
            kind=kind,
            stage=self.policy.stage,
            gate_key=self.policy.gate_key,
            candidate_id=candidate.candidate_id,
            selected_candidate_id=candidate.candidate_id,
            expected_selection_version=expected,
            unresolved_defects=(
                candidate.evaluation.defects
                if kind is GateOutcomeKind.DEGRADED_ACCEPTED
                else ()
            ),
            reason=reason,
        )
        self._terminal = outcome
        return outcome

    def _terminal_without_selection(
        self,
        *,
        candidate: CandidateVersion,
        kind: GateOutcomeKind,
        reason: str,
    ) -> GateOutcome:
        outcome = GateOutcome(
            kind=kind,
            stage=self.policy.stage,
            gate_key=self.policy.gate_key,
            candidate_id=candidate.candidate_id,
            expected_selection_version=(
                candidate.evaluation.expected_selection_version
            ),
            unresolved_defects=candidate.evaluation.defects,
            reason=reason,
        )
        self._terminal = outcome
        return outcome

    def decide(
        self,
        *,
        proposed_repair: RepairProposal | None = None,
    ) -> GateOutcome:
        if self._terminal is not None:
            return self._terminal
        if self._pending_repair is not None:
            if (
                proposed_repair is not None
                and proposed_repair
                != self._pending_repair.repair_proposal
            ):
                raise QualityError("a repair is already admitted for this gate")
            return self._pending_repair
        if not self._candidates:
            raise QualityError("machine QC is mandatory before gate decision")
        latest = self._candidates[-1]
        certified = self._is_certified(latest)
        mode = self.policy.review_mode

        if latest.evaluation.judgment is MachineJudgment.PASS:
            if mode is HumanReviewMode.ALL:
                return self._terminal_without_selection(
                    candidate=latest,
                    kind=GateOutcomeKind.WAITING_HUMAN,
                    reason="ALL policy requires human review after machine QC",
                )
            if not certified:
                if mode is HumanReviewMode.OFF:
                    return self._terminal_without_selection(
                        candidate=latest,
                        kind=GateOutcomeKind.BLOCKED_UNCERTIFIED,
                        reason=(
                            "uncertified evaluator cannot authorize unattended "
                            "stage release"
                        ),
                    )
                return self._terminal_without_selection(
                    candidate=latest,
                    kind=GateOutcomeKind.WAITING_HUMAN,
                    reason="uncertified machine result requires human authority",
                )
            return self._seal(
                candidate=latest,
                kind=GateOutcomeKind.SELECTED,
                reason="certified machine QC passed",
            )

        if proposed_repair is not None:
            if (
                proposed_repair.project_id != self.policy.project_id
                or proposed_repair.workflow_run_id
                != self.policy.workflow_run_id
            ):
                raise QualityError("repair proposal scope mismatch")
            if proposed_repair.stage != self.policy.stage:
                raise QualityError(
                    "repair cannot return to a sealed upstream stage"
                )
            if proposed_repair.gate_key != self.policy.gate_key:
                raise QualityError("repair proposal gate mismatch")
            if (
                set(proposed_repair.target_node_ids)
                != set(proposed_repair.target_node_stages)
                or any(
                    target_stage is not self.policy.stage
                    for target_stage
                    in proposed_repair.target_node_stages.values()
                )
            ):
                raise QualityError(
                    "repair targets cannot leave the current stage"
                )
            if proposed_repair.parent_candidate_id != latest.candidate_id:
                raise QualityError("repair must derive from latest candidate")
            next_usage = self._actual_repair_usage.plus(
                proposed_repair.estimated_usage
            )
            next_count = len(self._candidates)
            if self.policy.budget.permits(
                repair_count=next_count,
                usage=next_usage,
            ):
                self._pending_repair = GateOutcome(
                    kind=GateOutcomeKind.REWORK_PLANNED,
                    stage=self.policy.stage,
                    gate_key=self.policy.gate_key,
                    candidate_id=latest.candidate_id,
                    expected_selection_version=(
                        latest.evaluation.expected_selection_version
                    ),
                    unresolved_defects=latest.evaluation.defects,
                    repair_proposal=proposed_repair,
                    reason="same-stage repair reserved within all budgets",
                )
                return self._pending_repair

        if mode is not HumanReviewMode.OFF:
            return self._terminal_without_selection(
                candidate=latest,
                kind=GateOutcomeKind.WAITING_HUMAN,
                reason="repair exhausted with human review enabled",
            )

        certified_candidates = [
            item for item in self._candidates if self._is_certified(item)
        ]
        if (
            self.policy.exhaustion_policy
            is GateExhaustionPolicy.BLOCK
        ):
            return self._terminal_without_selection(
                candidate=latest,
                kind=GateOutcomeKind.BLOCKED_UNCERTIFIED,
                reason="repair exhausted and policy requires blocking",
            )
        if not certified_candidates:
            return self._terminal_without_selection(
                candidate=latest,
                kind=GateOutcomeKind.BLOCKED_UNCERTIFIED,
                reason=(
                    "repair exhausted and no certified candidate may authorize "
                    "unattended release"
                ),
            )
        best = max(certified_candidates, key=self._rank)
        return self._seal(
            candidate=best,
            kind=GateOutcomeKind.DEGRADED_ACCEPTED,
            reason=(
                "repair exhausted; selected certified best-of-N with unresolved "
                "defects"
            ),
        )
