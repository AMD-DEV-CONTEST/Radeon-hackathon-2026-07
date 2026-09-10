"""Private contract validation shared by repair selection and guardrails."""

from __future__ import annotations

from specstyle.domain.artifacts import ArtifactRef as _ArtifactRef
from specstyle.domain.enums import RuleLevel as _RuleLevel
from specstyle.domain.enums import RuleStatus as _RuleStatus
from specstyle.domain.enums import StaticApplicability as _StaticApplicability
from specstyle.domain.identifiers import ArtifactId as _ArtifactId
from specstyle.domain.identifiers import DecisionId as _DecisionId
from specstyle.domain.identifiers import Identifier as _Identifier
from specstyle.domain.identifiers import RuleId as _RuleId
from specstyle.domain.identifiers import Sha256 as _Sha256
from specstyle.errors import DomainError as _DomainError
from specstyle.generation.requests import GenerationRequest as _GenerationRequest
from specstyle.generation.seed_policy import SeedSnapshot as _SeedSnapshot
from specstyle.repair.models import RepairDecision as _RepairDecision
from specstyle.spec.compiled_models import CompiledRule as _CompiledRule
from specstyle.spec.compiled_models import CompiledThresholdBinding as _Binding
from specstyle.spec.compiled_models import CompiledVerificationPlan as _Plan
from specstyle.spec.compiled_models import ResourcePin as _Pin
from specstyle.verification.rule_models import GatePolicy as _GatePolicy
from specstyle.verification.rule_models import RuleDefinition as _Definition
from specstyle.verification.rule_models import RuleResult as _Result
from specstyle.verification.rule_models import VerificationReport as _Report


def _safe(message: str, callback):
    try:
        return callback()
    except _DomainError:
        raise
    except Exception as error:
        raise _DomainError(message) from error


def _primitive(value: object, message: str) -> str:
    """Copy untrusted text into an exact built-in ``str`` without coercion."""
    if not isinstance(value, str):
        raise _DomainError(message)

    def _copy() -> str:
        copied = str.__str__(value)
        if type(copied) is not str:
            raise _DomainError(message)
        return copied

    return _safe(message, _copy)


def _identifier(
    value: object, expected: type[_Identifier], message: str
) -> _Identifier:
    if type(value) is not expected:
        raise _DomainError(message)
    return _safe(message, lambda: expected(_primitive(value.value, message)))


def _sha256(value: object, message: str) -> _Sha256:
    if type(value) is not _Sha256:
        raise _DomainError(message)
    return _safe(message, lambda: _Sha256(_primitive(value.value, message)))


def _decision_id(value: object) -> _DecisionId:
    return _identifier(value, _DecisionId, "invalid decision id")


def _pin(value: object) -> _Pin:
    if type(value) is not _Pin:
        raise _DomainError("invalid verification plan")
    return _safe(
        "invalid verification plan",
        lambda: _Pin(
            _primitive(value.id, "invalid verification plan"),
            _primitive(value.revision, "invalid verification plan"),
            _sha256(value.sha256, "invalid verification plan"),
        ),
    )


def _binding(value: object) -> _Binding | None:
    if value is None:
        return None
    if type(value) is not _Binding:
        raise _DomainError("invalid verification plan")
    return _safe(
        "invalid verification plan",
        lambda: _Binding(
            _pin(value.profile_pin),
            _primitive(value.logical_name, "invalid verification plan"),
            value.status,
            _identifier(value.metric_id, _Identifier, "invalid verification plan"),
            value.operator,
            value.value,
            _sha256(value.calibration_dataset_sha256, "invalid verification plan"),
            _sha256(value.validation_dataset_sha256, "invalid verification plan"),
            _sha256(value.annotation_protocol_sha256, "invalid verification plan"),
            None
            if value.production_approval_sha256 is None
            else _sha256(value.production_approval_sha256, "invalid verification plan"),
        ),
    )


def _definition(value: object) -> _Definition:
    if type(value) is not _Definition:
        raise _DomainError("invalid verification report")
    return _safe(
        "invalid verification report",
        lambda: _Definition(
            _identifier(value.rule_id, _RuleId, "invalid verification report"),
            value.level,
            value.scope,
            value.required,
            value.applicability,
            _GatePolicy(
                value.gate_policy.on_fail,
                value.gate_policy.on_unverifiable,
                value.gate_policy.on_warning,
            ),
        ),
    )


def _rule(value: object) -> _CompiledRule:
    if type(value) is not _CompiledRule:
        raise _DomainError("invalid verification plan")
    return _safe(
        "invalid verification plan",
        lambda: _CompiledRule(
            _definition(value.definition),
            _pin(value.verifier_pin),
            None
            if value.metric_id is None
            else _identifier(value.metric_id, _Identifier, "invalid verification plan"),
            _binding(value.threshold_binding),
            value.priority,
            _tuple_identifiers(value.affected_by_actions, "invalid verification plan"),
        ),
    )


def _tuple_identifiers(value: object, message: str) -> tuple[_Identifier, ...]:
    if type(value) is not tuple:
        raise _DomainError(message)
    return _safe(
        message,
        lambda: tuple(_identifier(item, _Identifier, message) for item in value),
    )


def _plan(value: object) -> _Plan:
    if type(value) is not _Plan or type(value.rules) is not tuple:
        raise _DomainError("invalid verification plan")

    def _build() -> _Plan:
        rebuilt = _Plan(
            value.output_profile,
            _pin(value.output_profile_pin),
            tuple(_rule(item) for item in value.rules),
            value.l3_status,
            value.l3_reason,
            None if value.l3_plugin_pin is None else _pin(value.l3_plugin_pin),
            None
            if value.l3_threshold_profile_pin is None
            else _pin(value.l3_threshold_profile_pin),
        )
        return rebuilt

    return _safe("invalid verification plan", _build)


def _artifact(value: object) -> _ArtifactRef:
    if type(value) is not _ArtifactRef:
        raise _DomainError("invalid verification report")
    return _safe(
        "invalid verification report",
        lambda: _ArtifactRef(
            _identifier(value.artifact_id, _ArtifactId, "invalid verification report"),
            _sha256(value.sha256, "invalid verification report"),
        ),
    )


def _result(value: object) -> _Result:
    if type(value) is not _Result or type(value.affected_artifact_ids) is not tuple:
        raise _DomainError("invalid verification report")
    return _safe(
        "invalid verification report",
        lambda: _Result(
            _identifier(value.rule_id, _RuleId, "invalid verification report"),
            value.status,
            tuple(
                _identifier(item, _ArtifactId, "invalid verification report")
                for item in value.affected_artifact_ids
            ),
            value.score,
        ),
    )


def _report(value: object) -> _Report:
    if (
        type(value) is not _Report
        or type(value.artifacts) is not tuple
        or type(value.rules) is not tuple
        or type(value.results) is not tuple
    ):
        raise _DomainError("invalid verification report")

    def _build() -> _Report:
        rebuilt = _Report(
            tuple(_artifact(item) for item in value.artifacts),
            tuple(_definition(item) for item in value.rules),
            tuple(_result(item) for item in value.results),
        )
        return rebuilt

    return _safe("invalid verification report", _build)


def _request(value: object) -> _GenerationRequest:
    if type(value) is not _GenerationRequest:
        raise _DomainError("invalid generation request")

    def _build() -> _GenerationRequest:
        original_seed = value.seed
        if type(original_seed) is not _SeedSnapshot:
            raise _DomainError("invalid generation request")
        expected_seed = _SeedSnapshot(
            _sha256(original_seed.source_sha256, "invalid generation request"),
            _sha256(original_seed.compiled_spec_hash, "invalid generation request"),
            _primitive(original_seed.output_profile, "invalid generation request"),
            original_seed.variation_index,
        )
        if (
            _primitive(original_seed.algorithm, "invalid generation request")
            != expected_seed.algorithm
            or type(original_seed.seed) is not int
            or original_seed.seed != expected_seed.seed
        ):
            raise _DomainError("invalid generation request")
        rebuilt = _GenerationRequest(
            value.job_id,
            value.attempt_id,
            value.parent_attempt_id,
            value.compiled_spec,
            value.generation_profile,
            value.output_profile,
            value.source,
            value.style_references,
            value.prompt,
            value.control_input,
            value.variation_index,
            value.environment_hash,
            value.execution_parameters,
        )
        if rebuilt.seed != expected_seed:
            raise _DomainError("invalid generation request")
        original_fingerprint = _sha256(
            value.generation_fingerprint, "invalid generation request"
        )
        original_request_hash = _sha256(
            value.request_hash, "invalid generation request"
        )
        if (
            original_fingerprint != rebuilt.generation_fingerprint
            or original_request_hash != rebuilt.request_hash
        ):
            raise _DomainError("invalid generation request")
        return rebuilt

    return _safe("invalid generation request", _build)


def _decision(value: object) -> _RepairDecision:
    if type(value) is not _RepairDecision:
        raise _DomainError("invalid repair decision")
    return _safe(
        "invalid repair decision",
        lambda: _RepairDecision(
            _decision_id(value.decision_id),
            value.policy_version,
            _identifier(value.trigger_rule_id, _RuleId, "invalid repair decision"),
            _identifier(value.action_id, _Identifier, "invalid repair decision"),
            value.patch,
        ),
    )


def _validated_plan_report(plan: object, report: object, target_id: object):
    rebuilt_plan, rebuilt_report = _plan(plan), _report(report)
    target = _identifier(target_id, _ArtifactId, "invalid target artifact id")
    return _safe(
        "invalid repair context",
        lambda: _validate_plan_report(rebuilt_plan, rebuilt_report, target),
    )


def _validate_plan_report(plan: _Plan, report: _Report, target: _ArtifactId):
    if report.rules != plan.applicable_rule_definitions or target not in tuple(
        item.artifact_id for item in report.artifacts
    ):
        raise _DomainError("report does not match plan target")
    return plan, report, target


def _validated_context(
    request: object, plan: object, report: object, target_id: object
):
    request_value = _request(request)
    rebuilt_plan, rebuilt_report, target = _validated_plan_report(
        plan, report, target_id
    )
    return _safe(
        "invalid repair context",
        lambda: _validate_context(request_value, rebuilt_plan, rebuilt_report, target),
    )


def _validate_context(
    request: _GenerationRequest, plan: _Plan, report: _Report, target: _ArtifactId
):
    def _matches_plan():
        matches = tuple(
            _plan(item)
            for item in request.compiled_spec.verification_plans
            if item.output_profile == request.output_profile
        )
        if len(matches) != 1 or matches[0] != plan:
            raise _DomainError("plan does not match generation request")
        return request, plan, report, target

    return _safe("invalid repair context", _matches_plan)


def _result_for(report: _Report, rule_id: object, target: _ArtifactId) -> _Result:
    return _safe(
        "invalid verification report", lambda: _one_result(report, rule_id, target)
    )


def _one_result(report: _Report, rule_id: object, target: _ArtifactId) -> _Result:
    matches = tuple(
        item
        for item in report.results
        if item.rule_id == rule_id and target in item.affected_artifact_ids
    )
    if len(matches) != 1:
        raise _DomainError("report result does not match target rule")
    return matches[0]


def _ordered_required(plan: _Plan) -> tuple[_CompiledRule, ...]:
    tiers = {_RuleLevel.L1: 0, _RuleLevel.L3: 1, _RuleLevel.L2: 2}
    return _safe(
        "invalid verification plan",
        lambda: tuple(
            sorted(
                (
                    item
                    for item in plan.rules
                    if item.definition.applicability is _StaticApplicability.APPLICABLE
                    and item.definition.required
                ),
                key=lambda item: (
                    tiers[item.definition.level],
                    item.priority,
                    item.definition.rule_id.value,
                ),
            )
        ),
    )


def _blocking_rules(
    plan: _Plan, report: _Report, target: _ArtifactId
) -> tuple[_CompiledRule, ...]:
    return _safe(
        "invalid verification report",
        lambda: tuple(
            item for item in _ordered_required(plan) if _blocking(item, report, target)
        ),
    )


def _blocking(rule: _CompiledRule, report: _Report, target: _ArtifactId) -> bool:
    status = _result_for(report, rule.definition.rule_id, target).status
    return status is _RuleStatus.FAIL or (
        status is _RuleStatus.WARNING
        and rule.definition.gate_policy.on_warning == "reject"
    )
