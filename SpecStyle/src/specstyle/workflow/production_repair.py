"""Pure production repair composition over the shared repair core."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.domain.enums import RuleLevel, RuleScope, StaticApplicability
from specstyle.domain.identifiers import AttemptId, DecisionId, JobId
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.repair.history import RepairHistory, start_repair_history
from specstyle.repair.loop import (
    NextGeneration,
    RepairTerminal,
    consume_repair_result,
    next_repair_step,
)
from specstyle.spec.compiled_models import CompiledStyleSpec, OutputProfile
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import ArtifactDecision, VerificationReport

__all__ = ()


@dataclass(frozen=True, slots=True)
class _InitialRepairComposition:
    history: RepairHistory
    step: NextGeneration | RepairTerminal
    selecting_decision: ArtifactDecision | None


@dataclass(frozen=True, slots=True)
class _RepairResultComposition:
    history: RepairHistory
    terminal: RepairTerminal


def _validate_repair_contract(
    compiled: CompiledStyleSpec, profile: OutputProfile, /
) -> None:
    if type(compiled) is not CompiledStyleSpec or type(profile) is not str:
        raise DomainError("production repair contract is unsupported")
    repair = compiled.source_spec.repair
    if compiled.source_spec.outputs.profiles != (profile,) or (
        repair.policy_version,
        repair.max_rounds,
        repair.stop_after_no_improvement,
    ) != ("1.0", 1, 1):
        raise DomainError("production repair contract is unsupported")
    batch = tuple(
        rule
        for plan in compiled.verification_plans
        if plan.output_profile == profile
        for rule in plan.rules
        if (
            rule.definition.scope is RuleScope.BATCH
            and rule.definition.applicability is StaticApplicability.APPLICABLE
        )
    )
    if batch and (
        len(batch) != 1
        or profile != "background_sequence"
        or batch[0].definition.level is not RuleLevel.L2
        or batch[0].definition.required
        or batch[0].metric_id is None
        or batch[0].metric_id.value != "batch_style_consistency"
        or batch[0].threshold_binding is None
        or batch[0].threshold_binding.status != "DRAFT"
        or batch[0].threshold_binding.operator != "<="
    ):
        raise DomainError("applicable batch verification is unsupported")
    if any(
        rule.definition.scope is RuleScope.BATCH
        and rule.definition.applicability is StaticApplicability.APPLICABLE
        for plan in compiled.verification_plans
        if plan.output_profile != profile
        for rule in plan.rules
    ):
        raise DomainError("applicable batch verification is unsupported")


def _repair_ids(
    job_id: JobId, profile: OutputProfile, /
) -> tuple[DecisionId, AttemptId]:
    if type(job_id) is not JobId or type(profile) is not str:
        raise DomainError("invalid production repair identifiers")
    return (
        DecisionId(f"{job_id.value}-d1-{profile}-0"),
        AttemptId(f"{job_id.value}-a1-{profile}-0"),
    )


def _compose_initial_repair(
    request: GenerationRequest,
    artifact: GeneratedArtifact,
    report: VerificationReport,
    /,
) -> _InitialRepairComposition:
    history = start_repair_history(request, artifact, report)
    decision_id, attempt_id = _repair_ids(request.job_id, request.output_profile)
    step = next_repair_step(history, decision_id, attempt_id)
    if type(step) is NextGeneration or (
        type(step) is RepairTerminal and step.no_action is not None
    ):
        selecting = decide_artifact(report, artifact.ref.artifact_id)
    elif type(step) is RepairTerminal:
        selecting = None
    else:
        raise DomainError("invalid production repair composition")
    return _InitialRepairComposition(history, step, selecting)


def _compose_repair_result(
    history: RepairHistory,
    command: NextGeneration,
    artifact: GeneratedArtifact,
    report: VerificationReport,
    /,
) -> _RepairResultComposition:
    observed = consume_repair_result(history, command, artifact, report)
    request = observed.current_request
    decision_id, attempt_id = _repair_ids(request.job_id, request.output_profile)
    terminal = next_repair_step(observed, decision_id, attempt_id)
    if type(terminal) is not RepairTerminal:
        raise DomainError("invalid production repair composition")
    return _RepairResultComposition(observed, terminal)
