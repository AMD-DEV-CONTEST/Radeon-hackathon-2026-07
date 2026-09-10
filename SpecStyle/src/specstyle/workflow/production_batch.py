"""Formal Production cohort lifecycle with one post-gate publication."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Protocol

from specstyle.domain.enums import (
    RepairStopReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import CompiledRule, CompiledVerificationPlan
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import (
    ArtifactDecision,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)

__all__ = (
    "BatchPublicationReceipt",
    "FrozenProductionCohort",
    "ProductionBatchCandidate",
    "ProductionBatchPhase",
    "ProductionBatchReservation",
    "ProductionBatchResult",
    "ProductionBatchTarget",
    "freeze_production_cohort",
    "reserve_production_batch",
    "run_atomic_production_batch",
)

_RESERVATION_SEAL = object()
_MANIFEST_SCHEMA = "specstyle.production.batch_manifest.v1"


def _invalid(label: str) -> DomainError:
    return DomainError(f"invalid production batch {label}")


class ProductionBatchPhase(StrEnum):
    CANDIDATES_READY = "CANDIDATES_READY"
    COHORT_FROZEN = "COHORT_FROZEN"
    BATCH_VERIFIED = "BATCH_VERIFIED"
    ROUTED = "ROUTED"
    EXPORT_STAGED = "EXPORT_STAGED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ProductionBatchTarget:
    target_cell_sha256: Sha256
    compiled_spec_sha256: Sha256
    l2_profile_approval_sha256: Sha256
    l3_profile_approval_sha256: Sha256
    runtime_contract_sha256: Sha256

    def __post_init__(self) -> None:
        if any(
            type(value) is not Sha256
            for value in (
                self.target_cell_sha256,
                self.compiled_spec_sha256,
                self.l2_profile_approval_sha256,
                self.l3_profile_approval_sha256,
                self.runtime_contract_sha256,
            )
        ):
            raise _invalid("target")


@dataclass(frozen=True, slots=True, init=False)
class ProductionBatchReservation:
    batch_id: Identifier
    target_cell_sha256: Sha256
    member_ids: tuple[Identifier, ...]
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("production batch reservations are issued only")


def reserve_production_batch(
    target_cell_sha256: Sha256,
    member_ids: tuple[Identifier, ...],
    *,
    batch_id: Identifier | None = None,
) -> ProductionBatchReservation:
    if (
        type(target_cell_sha256) is not Sha256
        or type(member_ids) is not tuple
        or not member_ids
        or any(type(item) is not Identifier for item in member_ids)
        or len(set(member_ids)) != len(member_ids)
        or batch_id is not None
        and type(batch_id) is not Identifier
    ):
        raise _invalid("reservation")
    selected = batch_id or Identifier(f"batch-{uuid.uuid4().hex}")
    issued = object.__new__(ProductionBatchReservation)
    for name, value in (
        ("batch_id", Identifier(selected.value)),
        ("target_cell_sha256", Sha256(target_cell_sha256.value)),
        ("member_ids", tuple(Identifier(item.value) for item in member_ids)),
        ("_seal", _RESERVATION_SEAL),
    ):
        object.__setattr__(issued, name, value)
    return issued


def _validate_reservation(value: object) -> ProductionBatchReservation:
    if (
        type(value) is not ProductionBatchReservation
        or value._seal is not _RESERVATION_SEAL
    ):
        raise _invalid("reservation")
    rebuilt = reserve_production_batch(
        value.target_cell_sha256, value.member_ids, batch_id=value.batch_id
    )
    if rebuilt != value:
        raise _invalid("reservation")
    return rebuilt


@dataclass(frozen=True, slots=True)
class ProductionBatchCandidate:
    member_id: Identifier
    seed: int
    artifact: GeneratedArtifact
    item_report: VerificationReport
    compiled_spec_sha256: Sha256

    def __post_init__(self) -> None:
        valid = (
            type(self.member_id) is Identifier
            and type(self.seed) is int
            and not isinstance(self.seed, bool)
            and 0 <= self.seed < 2**63
            and type(self.artifact) is GeneratedArtifact
            and type(self.item_report) is VerificationReport
            and type(self.compiled_spec_sha256) is Sha256
            and self.item_report.artifacts == (self.artifact.ref,)
            and hash_bytes(self.artifact.content) == self.artifact.ref.sha256
        )
        if not valid:
            raise _invalid("candidate")


@dataclass(frozen=True, slots=True)
class FrozenProductionCohort:
    batch_id: Identifier
    target_cell_sha256: Sha256
    expected_count: int
    member_ids: tuple[Identifier, ...]
    artifact_ids: tuple[ArtifactId, ...]
    artifact_sha256s: tuple[Sha256, ...]
    seeds: tuple[int, ...]
    compiled_spec_sha256: Sha256
    l2_profile_approval_sha256: Sha256
    l3_profile_approval_sha256: Sha256
    runtime_contract_sha256: Sha256
    manifest_sha256: Sha256


@dataclass(frozen=True, slots=True)
class BatchPublicationReceipt:
    bundle_name: str
    bundle_sha256: Sha256

    def __post_init__(self) -> None:
        if (
            type(self.bundle_name) is not str
            or not self.bundle_name
            or type(self.bundle_sha256) is not Sha256
        ):
            raise _invalid("publication")


@dataclass(frozen=True, slots=True)
class ProductionBatchResult:
    manifest: FrozenProductionCohort
    report: VerificationReport
    decisions: tuple[ArtifactDecision, ...]
    publication: BatchPublicationReceipt


class _StagedPublication(Protocol):
    def commit(self) -> BatchPublicationReceipt: ...

    def close(self) -> None: ...


class _Publisher(Protocol):
    def stage(
        self,
        manifest: FrozenProductionCohort,
        report: VerificationReport,
        decisions: tuple[ArtifactDecision, ...],
        candidates: tuple[ProductionBatchCandidate, ...],
    ) -> _StagedPublication: ...


class _Journal(Protocol):
    def record(
        self,
        batch_id: Identifier,
        phase: ProductionBatchPhase,
        binding_sha256: Sha256,
    ) -> None: ...


def _batch_rule(
    plan: CompiledVerificationPlan,
    l2_profile_approval_sha256: Sha256,
    l3_profile_approval_sha256: Sha256,
) -> CompiledRule:
    if (
        type(plan) is not CompiledVerificationPlan
        or plan.output_profile != "xhs_grid"
        or type(l2_profile_approval_sha256) is not Sha256
        or type(l3_profile_approval_sha256) is not Sha256
    ):
        raise _invalid("plan")
    selected = tuple(
        rule
        for rule in plan.rules
        if rule.definition.scope is RuleScope.BATCH
        and rule.definition.applicability is StaticApplicability.APPLICABLE
    )
    if len(selected) != 1:
        raise _invalid("plan")
    rule = selected[0]
    binding = rule.threshold_binding
    if (
        not rule.definition.required
        or rule.definition.level is not RuleLevel.L2
        or rule.metric_id is None
        or rule.metric_id.value != "batch_style_consistency"
        or binding is None
        or binding.status != "VALIDATED"
        or binding.operator != "<="
        or binding.production_approval_sha256 is None
        or binding.production_approval_sha256 != l2_profile_approval_sha256
    ):
        raise _invalid("plan")
    _l3_rule(plan, l3_profile_approval_sha256)
    return rule


def _l3_rule(
    plan: CompiledVerificationPlan, l3_profile_approval_sha256: Sha256
) -> CompiledRule:
    selected = tuple(
        rule
        for rule in plan.rules
        if rule.definition.level is RuleLevel.L3
        and rule.definition.scope is RuleScope.ITEM
        and rule.definition.applicability is StaticApplicability.APPLICABLE
        and rule.metric_id is not None
        and rule.metric_id.value == "structure_edge_similarity"
    )
    if len(selected) != 1:
        raise _invalid("plan")
    rule = selected[0]
    binding = rule.threshold_binding
    if (
        plan.l3_status != "APPLICABLE"
        or not rule.definition.required
        or binding is None
        or binding.status != "VALIDATED"
        or binding.operator != ">="
        or binding.profile_pin != plan.l3_threshold_profile_pin
        or binding.production_approval_sha256 is None
        or binding.production_approval_sha256 != l3_profile_approval_sha256
    ):
        raise _invalid("plan")
    return rule


def _item_definitions(plan: CompiledVerificationPlan) -> tuple[RuleDefinition, ...]:
    return tuple(
        definition
        for definition in plan.applicable_rule_definitions
        if definition.scope is RuleScope.ITEM
    )


def _validate_candidates(
    reservation: ProductionBatchReservation,
    target: ProductionBatchTarget,
    plan: CompiledVerificationPlan,
    candidates: object,
) -> tuple[ProductionBatchCandidate, ...]:
    expected_rules = _item_definitions(plan)
    valid = (
        type(candidates) is tuple
        and len(candidates) == len(reservation.member_ids)
        and all(type(item) is ProductionBatchCandidate for item in candidates)
        and tuple(item.member_id for item in candidates) == reservation.member_ids
        and len({item.artifact.ref.artifact_id for item in candidates})
        == len(candidates)
        and len({item.artifact.ref.sha256 for item in candidates}) == len(candidates)
        and all(
            item.compiled_spec_sha256 == target.compiled_spec_sha256
            for item in candidates
        )
        and all(item.item_report.rules == expected_rules for item in candidates)
    )
    if not valid:
        raise _invalid("cohort")
    return candidates


def _manifest_material(
    reservation: ProductionBatchReservation,
    target: ProductionBatchTarget,
    candidates: tuple[ProductionBatchCandidate, ...],
) -> dict[str, object]:
    return {
        "batch_id": reservation.batch_id.value,
        "compiled_spec_sha256": target.compiled_spec_sha256.value,
        "expected_count": len(reservation.member_ids),
        "l2_profile_approval_sha256": target.l2_profile_approval_sha256.value,
        "l3_profile_approval_sha256": target.l3_profile_approval_sha256.value,
        "members": [
            {
                "artifact_id": item.artifact.ref.artifact_id.value,
                "artifact_sha256": item.artifact.ref.sha256.value,
                "member_id": item.member_id.value,
                "seed": item.seed,
            }
            for item in candidates
        ],
        "runtime_contract_sha256": target.runtime_contract_sha256.value,
        "schema_version": _MANIFEST_SCHEMA,
        "target_cell_sha256": target.target_cell_sha256.value,
    }


def _batch_result_binding(
    manifest: FrozenProductionCohort, result: RuleResult
) -> Sha256:
    encoded = json.dumps(
        {
            "affected_artifact_ids": [
                item.value for item in result.affected_artifact_ids
            ],
            "manifest_sha256": manifest.manifest_sha256.value,
            "rule_id": result.rule_id.value,
            "score": None if result.score is None else result.score.hex(),
            "status": result.status.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hash_bytes(encoded)


def _routing_binding(
    batch_binding: Sha256, decisions: tuple[ArtifactDecision, ...]
) -> Sha256:
    encoded = json.dumps(
        {
            "batch_result_sha256": batch_binding.value,
            "decisions": [
                {
                    "accepted_with_override": item.accepted_with_override,
                    "artifact_id": item.artifact_id.value,
                    "artifact_status": item.artifact_status.value,
                    "decision_reason": item.decision_reason.value,
                    "repair_stop_reason": (
                        None
                        if item.repair_stop_reason is None
                        else item.repair_stop_reason.value
                    ),
                }
                for item in decisions
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hash_bytes(encoded)


def freeze_production_cohort(
    reservation: ProductionBatchReservation,
    target: ProductionBatchTarget,
    plan: CompiledVerificationPlan,
    candidates: tuple[ProductionBatchCandidate, ...],
) -> FrozenProductionCohort:
    reservation = _validate_reservation(reservation)
    if (
        type(target) is not ProductionBatchTarget
        or reservation.target_cell_sha256 != target.target_cell_sha256
    ):
        raise _invalid("target")
    _batch_rule(
        plan,
        target.l2_profile_approval_sha256,
        target.l3_profile_approval_sha256,
    )
    candidates = _validate_candidates(reservation, target, plan, candidates)
    encoded = json.dumps(
        _manifest_material(reservation, target, candidates),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FrozenProductionCohort(
        reservation.batch_id,
        target.target_cell_sha256,
        len(candidates),
        reservation.member_ids,
        tuple(item.artifact.ref.artifact_id for item in candidates),
        tuple(item.artifact.ref.sha256 for item in candidates),
        tuple(item.seed for item in candidates),
        target.compiled_spec_sha256,
        target.l2_profile_approval_sha256,
        target.l3_profile_approval_sha256,
        target.runtime_contract_sha256,
        hash_bytes(encoded),
    )


def _validate_batch_result(
    rule: CompiledRule,
    candidates: tuple[ProductionBatchCandidate, ...],
    result: object,
) -> RuleResult:
    ids = tuple(item.artifact.ref.artifact_id for item in candidates)
    if (
        type(result) is not RuleResult
        or result.rule_id != rule.definition.rule_id
        or result.affected_artifact_ids != ids
        or result.status
        not in {RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.UNVERIFIABLE}
        or (result.status is RuleStatus.UNVERIFIABLE) != (result.score is None)
    ):
        raise _invalid("result")
    return result


def _final_report(
    plan: CompiledVerificationPlan,
    candidates: tuple[ProductionBatchCandidate, ...],
    batch_result: RuleResult,
) -> VerificationReport:
    rules = plan.applicable_rule_definitions
    item_results = tuple(
        result
        for rule in _item_definitions(plan)
        for candidate in candidates
        for result in candidate.item_report.results
        if result.rule_id == rule.rule_id
    )
    return VerificationReport(
        tuple(item.artifact.ref for item in candidates),
        rules,
        (*item_results, batch_result),
    )


def _checkpoint(
    phase: ProductionBatchPhase,
    callback: Callable[[ProductionBatchPhase], None],
    cancelled: Callable[[], bool],
) -> None:
    callback(phase)
    if cancelled():
        raise DomainError("production batch cancelled")


def _persist(
    journal: _Journal | None,
    batch_id: Identifier,
    phase: ProductionBatchPhase,
    binding_sha256: Sha256,
) -> None:
    if journal is not None:
        journal.record(batch_id, phase, binding_sha256)


def _stop_reason(
    report: VerificationReport, artifact_id: ArtifactId
) -> RepairStopReason:
    rules = {rule.rule_id: rule for rule in report.rules}
    required = tuple(
        result
        for result in report.results
        if artifact_id in result.affected_artifact_ids
        and rules[result.rule_id].required
        and rules[result.rule_id].applicability is StaticApplicability.APPLICABLE
    )
    if any(result.status is RuleStatus.UNVERIFIABLE for result in required):
        return RepairStopReason.UNVERIFIABLE
    if any(result.status is not RuleStatus.PASS for result in required):
        return RepairStopReason.NO_IMPROVEMENT
    return RepairStopReason.PASS_ALL_REQUIRED


def run_atomic_production_batch(
    reservation: ProductionBatchReservation,
    target: ProductionBatchTarget,
    plan: CompiledVerificationPlan,
    build_candidates: Callable[[ProductionBatchReservation], object],
    verify_batch: Callable[
        [FrozenProductionCohort, tuple[ProductionBatchCandidate, ...], CompiledRule],
        object,
    ],
    publisher: _Publisher,
    *,
    checkpoint: Callable[[ProductionBatchPhase], None] = lambda _phase: None,
    cancelled: Callable[[], bool] = lambda: False,
    journal: _Journal | None = None,
) -> ProductionBatchResult:
    reservation = _validate_reservation(reservation)
    rule = _batch_rule(
        plan,
        target.l2_profile_approval_sha256,
        target.l3_profile_approval_sha256,
    )
    candidates = _validate_candidates(
        reservation, target, plan, build_candidates(reservation)
    )
    manifest = freeze_production_cohort(reservation, target, plan, candidates)
    _persist(
        journal,
        reservation.batch_id,
        ProductionBatchPhase.CANDIDATES_READY,
        manifest.manifest_sha256,
    )
    _checkpoint(ProductionBatchPhase.CANDIDATES_READY, checkpoint, cancelled)
    _persist(
        journal,
        reservation.batch_id,
        ProductionBatchPhase.COHORT_FROZEN,
        manifest.manifest_sha256,
    )
    _checkpoint(ProductionBatchPhase.COHORT_FROZEN, checkpoint, cancelled)
    batch_result = _validate_batch_result(
        rule, candidates, verify_batch(manifest, candidates, rule)
    )
    batch_binding = _batch_result_binding(manifest, batch_result)
    _persist(
        journal,
        reservation.batch_id,
        ProductionBatchPhase.BATCH_VERIFIED,
        batch_binding,
    )
    _checkpoint(ProductionBatchPhase.BATCH_VERIFIED, checkpoint, cancelled)
    report = _final_report(plan, candidates, batch_result)
    decisions = tuple(
        decide_artifact(
            report,
            item.artifact.ref.artifact_id,
            repair_stop_reason=_stop_reason(report, item.artifact.ref.artifact_id),
        )
        for item in candidates
    )
    routing_binding = _routing_binding(batch_binding, decisions)
    _persist(
        journal,
        reservation.batch_id,
        ProductionBatchPhase.ROUTED,
        routing_binding,
    )
    _checkpoint(ProductionBatchPhase.ROUTED, checkpoint, cancelled)
    staged = publisher.stage(manifest, report, decisions, candidates)
    if not callable(getattr(staged, "commit", None)) or not callable(
        getattr(staged, "close", None)
    ):
        raise _invalid("publisher")
    try:
        _persist(
            journal,
            reservation.batch_id,
            ProductionBatchPhase.EXPORT_STAGED,
            routing_binding,
        )
        _checkpoint(ProductionBatchPhase.EXPORT_STAGED, checkpoint, cancelled)
        publication = staged.commit()
    except BaseException:
        staged.close()
        raise
    if type(publication) is not BatchPublicationReceipt:
        raise _invalid("publication")
    _persist(
        journal,
        reservation.batch_id,
        ProductionBatchPhase.COMPLETED,
        publication.bundle_sha256,
    )
    _checkpoint(ProductionBatchPhase.COMPLETED, checkpoint, lambda: False)
    return ProductionBatchResult(manifest, report, decisions, publication)
