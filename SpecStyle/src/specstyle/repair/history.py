"""Immutable, replay-validated repair provenance."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, fields, is_dataclass

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import ArtifactId, Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationParameters, GenerationRequest
from specstyle.repair.actions import build_repair_request, repair_policy_from_request
from specstyle.repair.guardrails import is_repair_improvement
from specstyle.repair.models import RepairDecision
from specstyle.repair.policies import select_repair
from specstyle.repair.conflict_resolution import _decision, _plan, _report, _request
from specstyle.spec.compiled_models import CompiledVerificationPlan
from specstyle.verification.rule_models import VerificationReport

RepairStateKey = tuple[GenerationParameters, int]


def _id(value: object, kind: type[Identifier]) -> Identifier:
    if type(value) is not kind or type(value.value) is not str:
        raise DomainError("invalid repair history")
    return kind(str.__str__(value.value))


def _sha(value: object) -> Sha256:
    if type(value) is not Sha256 or type(value.value) is not str:
        raise DomainError("invalid repair history")
    return Sha256(str.__str__(value.value))


def _artifact(value: object) -> GeneratedArtifact:
    if type(value) is not GeneratedArtifact or type(value.content) is not bytes:
        raise DomainError("invalid repair history")
    ref = value.ref
    if type(ref) is not ArtifactRef:
        raise DomainError("invalid repair history")
    return GeneratedArtifact(
        ArtifactRef(_id(ref.artifact_id, ArtifactId), _sha(ref.sha256)),
        bytes(value.content),
        _sha(value.request_hash),
        _sha(value.generation_fingerprint),
    )


def _state(request: GenerationRequest) -> RepairStateKey:
    parameters = request.execution_parameters
    if (
        type(parameters) is not GenerationParameters
        or type(request.variation_index) is not int
        or not 0 <= request.variation_index < 2**31
    ):
        raise DomainError("invalid repair history")
    return (
        GenerationParameters(
            parameters.ip_adapter_scale,
            parameters.img2img_strength,
            parameters.controlnet_scale,
        ),
        request.variation_index,
    )


def _state_key(value: RepairStateKey) -> tuple[str, str, str, int]:
    if type(value) is not tuple or len(value) != 2:
        raise DomainError("invalid repair history")
    parameters, variation = value
    if (
        type(parameters) is not GenerationParameters
        or type(variation) is not int
        or not 0 <= variation < 2**31
    ):
        raise DomainError("invalid repair history")
    parameters = GenerationParameters(
        parameters.ip_adapter_scale,
        parameters.img2img_strength,
        parameters.controlnet_scale,
    )
    return (
        parameters.ip_adapter_scale.hex(),
        parameters.img2img_strength.hex(),
        parameters.controlnet_scale.hex(),
        variation,
    )


def _request_key(value: GenerationRequest) -> tuple[object, ...]:
    return _canonical(value)


def _trusted_request(value: object) -> GenerationRequest:
    request = _request(value)
    _canonical(request)
    return request


def _canonical(value: object) -> tuple[object, ...]:
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is str:
        return ("str", str.__str__(value))
    if type(value) is bytes:
        return ("bytes", bytes(value))
    if type(value) is Sha256 or isinstance(value, Identifier):
        return (
            "identifier",
            type(value).__module__,
            type(value).__qualname__,
            _text(value.value),
        )
    if isinstance(value, enum.Enum):
        return (
            "enum",
            type(value).__module__,
            type(value).__qualname__,
            _text(value.value),
        )
    if type(value) is tuple:
        return ("tuple", tuple(_canonical(item) for item in value))
    if type(value) is list:
        return ("list", tuple(_canonical(item) for item in value))
    if type(value) is dict:
        pairs = tuple(
            (_canonical(key), _canonical(item)) for key, item in value.items()
        )
        return ("dict", tuple(sorted(pairs, key=repr)))
    if is_dataclass(value) and not isinstance(value, type):
        return _dataclass_key(value)
    if hasattr(type(value), "model_fields"):
        return _model_key(value)
    raise DomainError("invalid repair history")


def _text(value: object) -> str:
    if type(value) is not str:
        raise DomainError("invalid repair history")
    return str.__str__(value)


def _dataclass_key(value: object) -> tuple[object, ...]:
    return (
        "dataclass",
        type(value).__module__,
        type(value).__qualname__,
        tuple(
            (item.name, _canonical(getattr(value, item.name))) for item in fields(value)
        ),
    )


def _model_key(value: object) -> tuple[object, ...]:
    names = tuple(type(value).model_fields)
    return (
        "model",
        type(value).__module__,
        type(value).__qualname__,
        tuple((name, _canonical(getattr(value, name))) for name in names),
    )


def _decision_key(value: RepairDecision) -> tuple[object, ...]:
    patch = value.patch
    return (
        value.decision_id.value,
        value.policy_version,
        value.trigger_rule_id.value,
        value.action_id.value,
        *_state_key((patch.before_parameters, patch.before_variation_index)),
        *_state_key((patch.after_parameters, patch.after_variation_index)),
    )


def _rules_key(report: VerificationReport) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            rule.rule_id.value,
            rule.level.value,
            rule.scope.value,
            rule.required,
            rule.applicability.value,
            rule.gate_policy.on_fail,
            rule.gate_policy.on_unverifiable,
            rule.gate_policy.on_warning,
        )
        for rule in report.rules
    )


def _cohort_key(report: VerificationReport) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item.artifact_id.value, item.sha256.value) for item in report.artifacts
    )


def _report_key(report: VerificationReport) -> tuple[object, ...]:
    return (
        _cohort_key(report),
        _rules_key(report),
        tuple(
            sorted(
                (
                    (
                        result.rule_id.value,
                        result.status.value,
                        tuple(item.value for item in result.affected_artifact_ids),
                        None if result.score is None else result.score.hex(),
                    )
                    for result in report.results
                ),
                key=repr,
            )
        ),
    )


def _plan_for(request: GenerationRequest) -> CompiledVerificationPlan:
    plans = tuple(
        _plan(item)
        for item in request.compiled_spec.verification_plans
        if item.output_profile == request.output_profile
    )
    if len(plans) != 1:
        raise DomainError("invalid repair history")
    return plans[0]


def _check_report(plan: CompiledVerificationPlan, report: VerificationReport) -> None:
    expected = tuple(
        (
            rule.rule_id.value,
            rule.level.value,
            rule.scope.value,
            rule.required,
            rule.applicability.value,
            rule.gate_policy.on_fail,
            rule.gate_policy.on_unverifiable,
            rule.gate_policy.on_warning,
        )
        for rule in plan.applicable_rule_definitions
    )
    if _rules_key(report) != expected:
        raise DomainError("invalid repair history")


def _check_initial(
    request: GenerationRequest, artifact: GeneratedArtifact, report: VerificationReport
) -> None:
    if request.parent_attempt_id is not None:
        raise DomainError("invalid initial repair attempt")
    graph = request.graph
    defaults = GenerationParameters(
        graph.ip_adapter_scale, graph.img2img_strength, graph.controlnet_scale
    )
    parameters, variation_index = _state(request)
    if not 0 <= variation_index < 2**31 or _state_key(
        (parameters, variation_index)
    ) != _state_key((defaults, variation_index)):
        raise DomainError("invalid initial repair attempt")
    if (
        artifact.request_hash.value != request.request_hash.value
        or artifact.generation_fingerprint.value != request.generation_fingerprint.value
    ):
        raise DomainError("invalid initial repair attempt")
    if (artifact.ref.artifact_id.value, artifact.ref.sha256.value) not in _cohort_key(
        report
    ):
        raise DomainError("invalid initial repair attempt")
    _check_report(_plan_for(request), report)


@dataclass(frozen=True, slots=True)
class InitialAttempt:
    request: GenerationRequest
    artifact: GeneratedArtifact
    report: VerificationReport

    def __post_init__(self) -> None:
        try:
            request, artifact, report = (
                _trusted_request(self.request),
                _artifact(self.artifact),
                _report(self.report),
            )
            _check_initial(request, artifact, report)
        except Exception:
            raise DomainError("invalid initial repair attempt") from None
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "artifact", artifact)
        object.__setattr__(self, "report", report)


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    parent_report: VerificationReport
    decision: RepairDecision
    request: GenerationRequest
    artifact: GeneratedArtifact
    report: VerificationReport

    def __post_init__(self) -> None:
        try:
            values = (
                _report(self.parent_report),
                _decision(self.decision),
                _trusted_request(self.request),
                _artifact(self.artifact),
                _report(self.report),
            )
        except Exception:
            raise DomainError("invalid repair attempt") from None
        for name, value in zip(
            ("parent_report", "decision", "request", "artifact", "report"), values
        ):
            object.__setattr__(self, name, value)


def _replay(
    initial: InitialAttempt, attempts: tuple[RepairAttempt, ...]
) -> tuple[int, int, tuple[RepairStateKey, ...]]:
    request, artifact, report = initial.request, initial.artifact, initial.report
    seen = (_state(request),)
    no_improvement = 0
    attempt_ids = {request.attempt_id.value}
    artifact_ids = {artifact.ref.artifact_id.value}
    decision_ids: set[str] = set()
    for attempt in attempts:
        plan = _plan_for(request)
        if _report_key(attempt.parent_report) != _report_key(report):
            raise DomainError("invalid repair history")
        selected = select_repair(
            request,
            plan,
            report,
            artifact.ref.artifact_id,
            attempt.decision.decision_id,
            seen,
        )
        if type(selected) is not RepairDecision or _decision_key(
            selected
        ) != _decision_key(attempt.decision):
            raise DomainError("invalid repair history")
        expected = build_repair_request(
            request, attempt.decision, attempt.request.attempt_id
        )
        if _request_key(expected) != _request_key(attempt.request):
            raise DomainError("invalid repair history")
        if (
            attempt.request.attempt_id.value in attempt_ids
            or attempt.decision.decision_id.value in decision_ids
            or attempt.artifact.ref.artifact_id.value in artifact_ids
        ):
            raise DomainError("invalid repair history")
        if (
            attempt.artifact.request_hash.value != attempt.request.request_hash.value
            or attempt.artifact.generation_fingerprint.value
            != attempt.request.generation_fingerprint.value
        ):
            raise DomainError("invalid repair history")
        _check_report(plan, attempt.report)
        parent_cohort, child_cohort = _cohort_key(report), _cohort_key(attempt.report)
        target_slot = next(
            (
                index
                for index, ref in enumerate(parent_cohort)
                if ref == (artifact.ref.artifact_id.value, artifact.ref.sha256.value)
            ),
            None,
        )
        if (
            target_slot is None
            or len(parent_cohort) != len(child_cohort)
            or any(
                parent_cohort[index] != child_cohort[index]
                for index in range(len(parent_cohort))
                if index != target_slot
            )
        ):
            raise DomainError("invalid repair history")
        if child_cohort[target_slot] != (
            attempt.artifact.ref.artifact_id.value,
            attempt.artifact.ref.sha256.value,
        ):
            raise DomainError("invalid repair history")
        improved = is_repair_improvement(
            plan,
            report,
            attempt.report,
            artifact.ref.artifact_id,
            attempt.artifact.ref.artifact_id,
            attempt.decision,
        )
        no_improvement = 0 if improved else no_improvement + 1
        next_state = _state(attempt.request)
        if _state_key(next_state) in {_state_key(item) for item in seen}:
            raise DomainError("invalid repair history")
        seen += (next_state,)
        attempt_ids.add(attempt.request.attempt_id.value)
        artifact_ids.add(attempt.artifact.ref.artifact_id.value)
        decision_ids.add(attempt.decision.decision_id.value)
        request, artifact, report = attempt.request, attempt.artifact, attempt.report
    if len(attempts) > repair_policy_from_request(request).max_rounds:
        raise DomainError("invalid repair history")
    return len(attempts), no_improvement, seen


@dataclass(frozen=True, slots=True)
class RepairHistory:
    initial_attempt: InitialAttempt
    repair_attempts: tuple[RepairAttempt, ...] = ()
    rounds: int = field(init=False)
    consecutive_no_improvement: int = field(init=False)
    seen_state_keys: tuple[RepairStateKey, ...] = field(init=False)

    def __post_init__(self) -> None:
        try:
            if (
                type(self.initial_attempt) is not InitialAttempt
                or type(self.repair_attempts) is not tuple
                or any(type(item) is not RepairAttempt for item in self.repair_attempts)
            ):
                raise DomainError("invalid repair history")
            initial = InitialAttempt(
                self.initial_attempt.request,
                self.initial_attempt.artifact,
                self.initial_attempt.report,
            )
            attempts = tuple(
                RepairAttempt(
                    item.parent_report,
                    item.decision,
                    item.request,
                    item.artifact,
                    item.report,
                )
                for item in self.repair_attempts
            )
            rounds, no_improvement, seen = _replay(initial, attempts)
        except Exception:
            raise DomainError("invalid repair history") from None
        object.__setattr__(self, "initial_attempt", initial)
        object.__setattr__(self, "repair_attempts", attempts)
        object.__setattr__(self, "rounds", rounds)
        object.__setattr__(self, "consecutive_no_improvement", no_improvement)
        object.__setattr__(self, "seen_state_keys", seen)

    @property
    def current_request(self) -> GenerationRequest:
        return (
            self.initial_attempt.request
            if not self.repair_attempts
            else self.repair_attempts[-1].request
        )

    @property
    def current_artifact(self) -> GeneratedArtifact:
        return (
            self.initial_attempt.artifact
            if not self.repair_attempts
            else self.repair_attempts[-1].artifact
        )

    @property
    def current_report(self) -> VerificationReport:
        return (
            self.initial_attempt.report
            if not self.repair_attempts
            else self.repair_attempts[-1].report
        )

    @property
    def current_target_artifact_id(self) -> ArtifactId:
        return self.current_artifact.ref.artifact_id


def _trusted_history(value: object) -> RepairHistory:
    if type(value) is not RepairHistory:
        raise DomainError("invalid repair history")
    rebuilt = RepairHistory(value.initial_attempt, value.repair_attempts)
    if (
        type(value.rounds) is not int
        or value.rounds != rebuilt.rounds
        or type(value.consecutive_no_improvement) is not int
        or value.consecutive_no_improvement != rebuilt.consecutive_no_improvement
        or type(value.seen_state_keys) is not tuple
    ):
        raise DomainError("invalid repair history")
    if tuple(_state_key(item) for item in value.seen_state_keys) != tuple(
        _state_key(item) for item in rebuilt.seen_state_keys
    ):
        raise DomainError("invalid repair history")
    return rebuilt


def start_repair_history(
    request: GenerationRequest,
    artifact: GeneratedArtifact,
    report: VerificationReport,
    /,
) -> RepairHistory:
    try:
        return RepairHistory(InitialAttempt(request, artifact, report))
    except Exception:
        raise DomainError("invalid repair history") from None
