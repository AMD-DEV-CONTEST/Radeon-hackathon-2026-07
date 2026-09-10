"""Production same-input semantic replay evidence and assessment."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Literal

from specstyle.domain.enums import RuleLevel, StaticApplicability
from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.exporting.bundle import ExportBundle
from specstyle.spec.models import StyleSpecV11
from specstyle.workflow.production_service import ProductionJobResult

ReplayStatus = Literal["EXACT", "COMPATIBLE", "REJECTED", "UNVERIFIABLE"]
MetricLevel = Literal["L2", "L3"]
MetricStatus = Literal["PASS", "FAIL", "WARNING", "UNVERIFIABLE"]
L3Status = Literal["APPLICABLE", "NOT_APPLICABLE"]

_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)


def _invalid() -> DomainError:
    return DomainError("invalid production replay evidence")


def _identity(value: object) -> bool:
    return type(value) is str and _IDENTITY.fullmatch(value) is not None


def _rebuild_sha(value: object) -> Sha256:
    if type(value) is not Sha256 or type(value.value) is not str:
        raise _invalid() from None
    try:
        return Sha256(str.__str__(value.value))
    except Exception:
        raise _invalid() from None


def _sha(value: object) -> bool:
    try:
        _rebuild_sha(value)
    except DomainError:
        return False
    return True


def _primitive(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Identifier, Sha256)):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _primitive(getattr(value, item.name))
            for item in dataclasses.fields(value)
            if item.init
        }
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    return value


def _canonical_hash(schema: str, value: object) -> Sha256:
    encoded = json.dumps(
        {"schema": schema, "value": _primitive(value)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return Sha256(hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True, slots=True)
class ReplayMetricObservation:
    level: MetricLevel
    rule_id: str
    metric_id: str
    status: MetricStatus
    score: float | None
    tolerance: float

    def __post_init__(self) -> None:
        if (
            self.level not in ("L2", "L3")
            or not _identity(self.rule_id)
            or not _identity(self.metric_id)
            or self.status not in ("PASS", "FAIL", "WARNING", "UNVERIFIABLE")
            or (
                self.score is not None
                and (type(self.score) is not float or not math.isfinite(self.score))
            )
            or type(self.tolerance) is not float
            or not math.isfinite(self.tolerance)
            or not 0.0 <= self.tolerance <= 1.0
        ):
            raise _invalid() from None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.level, self.rule_id, self.metric_id)


@dataclass(frozen=True, slots=True)
class ProductionReplayEvidence:
    job_id: str
    bundle_name: str
    bundle_sha256: Sha256
    artifact_sha256: Sha256
    form_fingerprint: Sha256
    compiled_spec_hash: Sha256
    graph_fingerprint: Sha256
    model_pins_fingerprint: Sha256
    generation_fingerprint: Sha256
    required_gate_fingerprint: Sha256
    required_gate_state_fingerprint: Sha256
    route_fingerprint: Sha256
    environment_fingerprint: Sha256
    environment_policy: Literal["advisory", "strict"]
    variation_index: int
    seed: int
    metrics: tuple[ReplayMetricObservation, ...]
    l3_status: L3Status
    l3_reason: str | None

    def __post_init__(self) -> None:
        try:
            hashes = tuple(_rebuild_sha(getattr(self, name)) for name in _HASH_FIELDS)
            if type(self.metrics) is not tuple:
                raise _invalid()
            metrics = tuple(
                ReplayMetricObservation(
                    item.level,
                    item.rule_id,
                    item.metric_id,
                    item.status,
                    item.score,
                    item.tolerance,
                )
                for item in self.metrics
                if type(item) is ReplayMetricObservation
            )
            metric_keys = tuple(item.key for item in metrics)
            if len(metrics) != len(self.metrics) or len(metric_keys) != len(
                set(metric_keys)
            ):
                raise _invalid()
            self._validate_scalars(hashes)
        except Exception:
            raise _invalid() from None
        for name, value in zip(_HASH_FIELDS, hashes, strict=True):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "metrics", metrics)

    def _validate_scalars(self, hashes: tuple[object, ...]) -> None:
        if (
            not _identity(self.job_id)
            or not _identity(self.bundle_name)
            or not all(_sha(value) for value in hashes)
            or self.environment_policy not in ("advisory", "strict")
            or type(self.variation_index) is not int
            or not 0 <= self.variation_index < 2**31
            or type(self.seed) is not int
            or not 0 <= self.seed < 2**63
            or self.l3_status not in ("APPLICABLE", "NOT_APPLICABLE")
            or (self.l3_status == "APPLICABLE") != (self.l3_reason is None)
            or (
                self.l3_reason is not None
                and (type(self.l3_reason) is not str or not self.l3_reason)
            )
        ):
            raise _invalid()


_HASH_FIELDS = (
    "bundle_sha256",
    "artifact_sha256",
    "form_fingerprint",
    "compiled_spec_hash",
    "graph_fingerprint",
    "model_pins_fingerprint",
    "generation_fingerprint",
    "required_gate_fingerprint",
    "required_gate_state_fingerprint",
    "route_fingerprint",
    "environment_fingerprint",
)


@dataclass(frozen=True, slots=True)
class ReplayMetricDelta:
    level: MetricLevel
    rule_id: str
    metric_id: str
    baseline: float
    candidate: float
    delta: float
    tolerance: float


@dataclass(frozen=True, slots=True)
class ProductionReplayAssessment:
    status: ReplayStatus
    mode: Literal["same_input"]
    reasons: tuple[str, ...]
    metrics: tuple[ReplayMetricDelta, ...]
    l3_status: L3Status
    artifact_hash_equal: bool


_IDENTITY_COMPARISONS = (
    ("form_fingerprint", "input_form_fingerprint_mismatch"),
    ("compiled_spec_hash", "compiled_spec_hash_mismatch"),
    ("graph_fingerprint", "compiled_graph_mismatch"),
    ("model_pins_fingerprint", "model_pins_mismatch"),
    ("generation_fingerprint", "generation_fingerprint_mismatch"),
    ("required_gate_fingerprint", "required_gate_mismatch"),
    ("required_gate_state_fingerprint", "required_gate_state_mismatch"),
    ("route_fingerprint", "route_mismatch"),
    ("variation_index", "variation_index_mismatch"),
    ("seed", "seed_mismatch"),
)


def _identity_reasons(
    baseline: ProductionReplayEvidence, candidate: ProductionReplayEvidence
) -> list[str]:
    reasons = [
        reason
        for field, reason in _IDENTITY_COMPARISONS
        if getattr(baseline, field) != getattr(candidate, field)
    ]
    if baseline.job_id == candidate.job_id:
        reasons.append("job_identity_reused")
    if baseline.bundle_name == candidate.bundle_name:
        reasons.append("bundle_identity_reused")
    if baseline.environment_policy != candidate.environment_policy:
        reasons.append("environment_policy_mismatch")
    if (baseline.l3_status, baseline.l3_reason) != (
        candidate.l3_status,
        candidate.l3_reason,
    ):
        reasons.append("l3_contract_mismatch")
    return reasons


def _metric_assessment(
    baseline: ProductionReplayEvidence, candidate: ProductionReplayEvidence
) -> tuple[list[str], list[str], tuple[ReplayMetricDelta, ...]]:
    left = {item.key: item for item in baseline.metrics}
    right = {item.key: item for item in candidate.metrics}
    rejected: list[str] = []
    unverifiable: list[str] = []
    deltas: list[ReplayMetricDelta] = []
    if not left and not right:
        unverifiable.append("no_applicable_replay_metrics")
    for key in sorted(left.keys() | right.keys()):
        before, after = left.get(key), right.get(key)
        label = ":".join(key[:2])
        if before is None or after is None:
            unverifiable.append(f"metric_missing:{label}")
            continue
        if before.score is None or after.score is None:
            unverifiable.append(f"metric_unscored:{label}")
            continue
        if before.tolerance != after.tolerance:
            rejected.append(f"metric_tolerance_mismatch:{label}")
            continue
        if before.status != after.status:
            rejected.append(f"metric_status_mismatch:{label}")
        delta = abs(after.score - before.score)
        deltas.append(
            ReplayMetricDelta(*key, before.score, after.score, delta, before.tolerance)
        )
        if delta > before.tolerance:
            rejected.append(f"metric_delta_exceeded:{label}")
    return rejected, unverifiable, tuple(deltas)


def assess_production_replay(
    baseline: ProductionReplayEvidence,
    candidate: ProductionReplayEvidence,
    /,
) -> ProductionReplayAssessment:
    baseline = _rebuild_evidence(baseline)
    candidate = _rebuild_evidence(candidate)
    rejected = _identity_reasons(baseline, candidate)
    metric_rejected, unverifiable, deltas = _metric_assessment(baseline, candidate)
    rejected.extend(metric_rejected)
    env_equal = baseline.environment_fingerprint == candidate.environment_fingerprint
    if not env_equal and baseline.environment_policy == "strict":
        rejected.append("environment_fingerprint_mismatch")
    if rejected:
        status: ReplayStatus = "REJECTED"
        reasons = tuple(rejected)
    elif unverifiable:
        status = "UNVERIFIABLE"
        reasons = tuple(unverifiable)
    elif not env_equal:
        status = "COMPATIBLE"
        reasons = ("environment_fingerprint_differs",)
    else:
        status = "EXACT"
        reasons = ()
    return ProductionReplayAssessment(
        status,
        "same_input",
        reasons,
        deltas,
        baseline.l3_status,
        baseline.artifact_sha256 == candidate.artifact_sha256,
    )


def _rebuild_evidence(value: object) -> ProductionReplayEvidence:
    if type(value) is not ProductionReplayEvidence:
        raise _invalid() from None
    try:
        return ProductionReplayEvidence(
            *(getattr(value, item.name) for item in dataclasses.fields(value))
        )
    except Exception:
        raise _invalid() from None


def _required_gate_material(result: ProductionJobResult) -> tuple[object, ...]:
    return tuple(
        rule
        for rule in result.verification_plan.rules
        if rule.definition.required
        and rule.definition.applicability is StaticApplicability.APPLICABLE
    )


def _required_state_material(result: ProductionJobResult) -> tuple[object, ...]:
    required = {
        rule.definition.rule_id
        for rule in result.verification_plan.rules
        if rule.definition.required
        and rule.definition.applicability is StaticApplicability.APPLICABLE
    }
    return tuple(
        sorted(
            (
                item.rule_id.value,
                item.status.value,
            )
            for item in result.report.results
            if item.rule_id in required
        )
    )


def _metric_observations(
    result: ProductionJobResult,
) -> tuple[ReplayMetricObservation, ...]:
    by_rule = {item.rule_id: item for item in result.report.results}
    tolerances = result.compiled.source_spec.replay_contract.tolerated_metric_delta
    observations = []
    for rule in result.verification_plan.rules:
        definition = rule.definition
        if (
            definition.level not in (RuleLevel.L2, RuleLevel.L3)
            or definition.applicability is not StaticApplicability.APPLICABLE
            or rule.metric_id is None
        ):
            continue
        outcome = by_rule.get(definition.rule_id)
        score = None if outcome is None else outcome.score
        status = "UNVERIFIABLE" if outcome is None else outcome.status.value
        tolerance = (
            tolerances.l2_style_fidelity
            if definition.level is RuleLevel.L2
            else tolerances.l3_fidelity
        )
        observations.append(
            ReplayMetricObservation(
                definition.level.value,
                definition.rule_id.value,
                rule.metric_id.value,
                status,
                score,
                float(tolerance),
            )
        )
    return tuple(sorted(observations, key=lambda item: item.key))


def _route_material(result: ProductionJobResult) -> tuple[object, ...]:
    decision = result.terminal.artifact_decision
    return (
        decision.artifact_status,
        decision.decision_reason,
        decision.repair_stop_reason,
        decision.accepted_with_override,
    )


def capture_production_replay_evidence(
    result: ProductionJobResult,
    bundle: ExportBundle,
    form_fingerprint: Sha256,
    /,
) -> ProductionReplayEvidence:
    if (
        type(result) is not ProductionJobResult
        or type(bundle) is not ExportBundle
        or not _sha(form_fingerprint)
    ):
        raise _invalid() from None
    initial = result.history.initial_attempt.request
    graph = initial.graph
    source_spec = result.compiled.source_spec
    environment_policy = (
        source_spec.replay_contract.environment_policy
        if type(source_spec) is StyleSpecV11
        else "advisory"
    )
    return ProductionReplayEvidence(
        initial.job_id.value,
        bundle.bundle_name,
        bundle.bundle_sha256,
        result.artifact.ref.sha256,
        form_fingerprint,
        result.compiled.compiled_spec_hash,
        _canonical_hash("specstyle.production.replay.graph.v1", graph),
        _canonical_hash(
            "specstyle.production.replay.model-pins.v1",
            (graph.base_model, graph.ip_adapter, graph.controlnet),
        ),
        initial.generation_fingerprint,
        _canonical_hash(
            "specstyle.production.replay.required-gates.v1",
            _required_gate_material(result),
        ),
        _canonical_hash(
            "specstyle.production.replay.required-gate-state.v1",
            _required_state_material(result),
        ),
        _canonical_hash(
            "specstyle.production.replay.route.v1", _route_material(result)
        ),
        initial.environment_hash,
        environment_policy,
        initial.variation_index,
        initial.seed.seed,
        _metric_observations(result),
        result.verification_plan.l3_status,
        result.verification_plan.l3_reason,
    )


__all__ = (
    "ProductionReplayAssessment",
    "ProductionReplayEvidence",
    "ReplayMetricDelta",
    "ReplayMetricObservation",
    "assess_production_replay",
    "capture_production_replay_evidence",
)
