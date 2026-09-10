"""Pure, two-phase repair state machine."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.domain.enums import ArtifactStatus, DecisionReason, RepairStopReason
from specstyle.domain.identifiers import (
    ArtifactId,
    AttemptId,
    DecisionId,
    Identifier,
    RuleId,
)
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.repair.actions import build_repair_request, repair_policy_from_request
from specstyle.repair.history import (
    RepairHistory,
    RepairAttempt,
    _decision_key,
    _id,
    _plan_for,
    _request_key,
    _trusted_request,
    _trusted_history,
)
from specstyle.repair.models import NoAction, RepairDecision
from specstyle.repair.policies import select_repair
from specstyle.repair.conflict_resolution import _decision, _report
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import ArtifactDecision, VerificationReport


def _terminal_decision(
    history: RepairHistory, stop: RepairStopReason
) -> ArtifactDecision:
    return decide_artifact(
        history.current_report,
        history.current_target_artifact_id,
        repair_stop_reason=stop,
    )


def _rebuild_artifact_decision(value: object) -> ArtifactDecision:
    if type(value) is not ArtifactDecision:
        raise DomainError("invalid repair terminal")
    return ArtifactDecision(
        _id(value.artifact_id, ArtifactId),
        value.artifact_status,
        value.decision_reason,
        value.repair_stop_reason,
        value.accepted_with_override,
    )


@dataclass(frozen=True, slots=True)
class NextGeneration:
    decision: RepairDecision
    request: GenerationRequest

    def __post_init__(self) -> None:
        try:
            decision, request = _decision(self.decision), _trusted_request(self.request)
        except Exception:
            raise DomainError("invalid next generation") from None
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "request", request)


@dataclass(frozen=True, slots=True)
class RepairTerminal:
    artifact_decision: ArtifactDecision
    no_action: NoAction | None

    def __post_init__(self) -> None:
        try:
            decision = _rebuild_artifact_decision(self.artifact_decision)
            no_action = (
                None if self.no_action is None else _rebuild_no_action(self.no_action)
            )
            if (no_action is None) != (
                decision.repair_stop_reason is not RepairStopReason.NO_ACTION
            ):
                raise DomainError("invalid repair terminal")
        except Exception:
            raise DomainError("invalid repair terminal") from None
        object.__setattr__(self, "artifact_decision", decision)
        object.__setattr__(self, "no_action", no_action)


RepairStep = NextGeneration | RepairTerminal


def _rebuild_no_action(value: object) -> NoAction:
    if type(value) is not NoAction:
        raise DomainError("invalid repair terminal")
    if (
        type(value.blocked_rule_ids) is not tuple
        or type(value.blocked_action_ids) is not tuple
        or value.stop_reason is not RepairStopReason.NO_ACTION
    ):
        raise DomainError("invalid repair terminal")
    return NoAction(
        _id(value.decision_id, DecisionId),
        tuple(_id(item, RuleId) for item in value.blocked_rule_ids),
        tuple(_id(item, Identifier) for item in value.blocked_action_ids),
    )


def _executed_decision_ids(history: RepairHistory) -> set[str]:
    return {attempt.decision.decision_id.value for attempt in history.repair_attempts}


def _attempt_ids(history: RepairHistory) -> set[str]:
    return {
        attempt.request.attempt_id.value
        for attempt in (history.initial_attempt, *history.repair_attempts)
    }


def _terminal(
    history: RepairHistory, stop: RepairStopReason, no_action: NoAction | None = None
) -> RepairTerminal:
    return RepairTerminal(_terminal_decision(history, stop), no_action)


def _stop_reason(history: RepairHistory) -> RepairStopReason | None:
    routed = decide_artifact(history.current_report, history.current_target_artifact_id)
    if (
        routed.artifact_status is ArtifactStatus.APPROVED
        and routed.decision_reason is DecisionReason.ALL_REQUIRED_PASS
    ):
        return RepairStopReason.PASS_ALL_REQUIRED
    if (
        routed.artifact_status is ArtifactStatus.REJECTED
        and routed.decision_reason is DecisionReason.REQUIRED_GATE_UNVERIFIABLE
    ):
        return RepairStopReason.UNVERIFIABLE
    if (
        routed.artifact_status is ArtifactStatus.MANUAL_REVIEW
        and routed.decision_reason is DecisionReason.MANUAL_POLICY
    ):
        return RepairStopReason.MANUAL_REQUEST
    policy = repair_policy_from_request(history.current_request)
    if history.consecutive_no_improvement >= policy.stop_after_no_improvement:
        return RepairStopReason.NO_IMPROVEMENT
    if history.rounds >= policy.max_rounds:
        return RepairStopReason.MAX_ROUNDS
    return None


def next_repair_step(
    history: RepairHistory, decision_id: DecisionId, next_attempt_id: AttemptId, /
) -> RepairStep:
    try:
        trusted = _trusted_history(history)
        decision = _id(decision_id, DecisionId)
        attempt = _id(next_attempt_id, AttemptId)
        stop = _stop_reason(trusted)
        if stop is not None:
            return _terminal(trusted, stop)
        if decision.value in _executed_decision_ids(trusted):
            raise DomainError("invalid repair transition")
        plan = _plan_for(trusted.current_request)
        selected = select_repair(
            trusted.current_request,
            plan,
            trusted.current_report,
            trusted.current_target_artifact_id,
            decision,
            trusted.seen_state_keys,
        )
        if type(selected) is NoAction:
            return _terminal(trusted, RepairStopReason.NO_ACTION, selected)
        if attempt.value in _attempt_ids(trusted):
            raise DomainError("invalid repair transition")
        return NextGeneration(
            selected, build_repair_request(trusted.current_request, selected, attempt)
        )
    except Exception:
        raise DomainError("invalid repair transition") from None


def consume_repair_result(
    history: RepairHistory,
    command: NextGeneration,
    artifact: GeneratedArtifact,
    report: VerificationReport,
    /,
) -> RepairHistory:
    try:
        trusted = _trusted_history(history)
        if type(command) is not NextGeneration:
            raise DomainError("invalid repair observation")
        command = NextGeneration(command.decision, command.request)
        artifact, report = artifact, _report(report)
        if command.decision.decision_id.value in _executed_decision_ids(
            trusted
        ) or command.request.attempt_id.value in _attempt_ids(trusted):
            raise DomainError("invalid repair observation")
        plan = _plan_for(trusted.current_request)
        selected = select_repair(
            trusted.current_request,
            plan,
            trusted.current_report,
            trusted.current_target_artifact_id,
            command.decision.decision_id,
            trusted.seen_state_keys,
        )
        expected = build_repair_request(
            trusted.current_request, command.decision, command.request.attempt_id
        )
        if (
            type(selected) is not RepairDecision
            or _decision_key(selected) != _decision_key(command.decision)
            or _request_key(expected) != _request_key(command.request)
        ):
            raise DomainError("invalid repair observation")
        return RepairHistory(
            trusted.initial_attempt,
            trusted.repair_attempts
            + (
                RepairAttempt(
                    trusted.current_report,
                    command.decision,
                    command.request,
                    artifact,
                    report,
                ),
            ),
        )
    except Exception:
        raise DomainError("invalid repair observation") from None
