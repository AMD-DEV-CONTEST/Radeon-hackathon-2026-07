"""Formal Production cohort lifecycle and publication ordering tests."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    ArtifactStatus,
    RepairStopReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, Identifier, RuleId
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import (
    CompiledRule,
    CompiledThresholdBinding,
    CompiledVerificationPlan,
    ResourcePin,
)
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)


def _pin(value: str) -> ResourcePin:
    return ResourcePin(value, "r1", hash_bytes(value.encode()))


def _definition(
    value: str, scope: RuleScope, level: RuleLevel | None = None
) -> RuleDefinition:
    return RuleDefinition(
        RuleId(value),
        level or (RuleLevel.L2 if scope is RuleScope.BATCH else RuleLevel.L1),
        scope,
        True,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", "reject", "manual_review"),
    )


def _plan(*, include_l3: bool = True) -> CompiledVerificationPlan:
    item = CompiledRule(
        _definition("item", RuleScope.ITEM), _pin("item"), None, None, 0, ()
    )
    metric = Identifier("batch_style_consistency")
    threshold = CompiledThresholdBinding(
        _pin("l2-profile"),
        "formal-l2",
        "VALIDATED",
        metric,
        "<=",
        0.25,
        hash_bytes(b"calibration"),
        hash_bytes(b"validation"),
        hash_bytes(b"protocol"),
        hash_bytes(b"approval"),
    )
    batch = CompiledRule(
        _definition("batch", RuleScope.BATCH),
        _pin("batch-verifier"),
        metric,
        threshold,
        1,
        (),
    )
    if not include_l3:
        return CompiledVerificationPlan(
            "xhs_grid",
            _pin("output"),
            (item, batch),
            "NOT_APPLICABLE",
            "NO_L3_CONFIG",
            None,
            None,
        )
    l3_metric = Identifier("structure_edge_similarity")
    l3_threshold = CompiledThresholdBinding(
        _pin("l3-profile"),
        "formal-l3",
        "VALIDATED",
        l3_metric,
        ">=",
        0.75,
        hash_bytes(b"l3-calibration"),
        hash_bytes(b"l3-validation"),
        hash_bytes(b"l3-protocol"),
        hash_bytes(b"l3-approval"),
    )
    l3 = CompiledRule(
        _definition("structure", RuleScope.ITEM, RuleLevel.L3),
        _pin("structure-verifier"),
        l3_metric,
        l3_threshold,
        2,
        (),
    )
    return CompiledVerificationPlan(
        "xhs_grid",
        _pin("output"),
        (item, l3, batch),
        "APPLICABLE",
        None,
        _pin("structure-plugin"),
        l3_threshold.profile_pin,
    )


def _png(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, "PNG")
    return output.getvalue()


def _candidate(member: str, index: int, plan: CompiledVerificationPlan):
    from specstyle.workflow.production_batch import ProductionBatchCandidate

    content = _png((20 + index, 40, 80))
    artifact = GeneratedArtifact(
        ArtifactRef(ArtifactId(f"artifact-{member}"), hash_bytes(content)),
        content,
        hash_bytes(f"request-{member}".encode()),
        hash_bytes(f"fingerprint-{member}".encode()),
    )
    item_rules = tuple(
        rule.definition
        for rule in plan.rules
        if rule.definition.scope is RuleScope.ITEM
    )
    report = VerificationReport(
        (artifact.ref,),
        item_rules,
        tuple(
            RuleResult(rule.rule_id, RuleStatus.PASS, (artifact.ref.artifact_id,), 1.0)
            for rule in item_rules
        ),
    )
    return ProductionBatchCandidate(
        Identifier(member), index + 100, artifact, report, hash_bytes(b"compiled")
    )


class _Staged:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.closed = False

    def commit(self):
        from specstyle.workflow.production_batch import BatchPublicationReceipt

        self.events.append("commit")
        return BatchPublicationReceipt("bundle", hash_bytes(b"bundle"))

    def close(self) -> None:
        self.closed = True
        self.events.append("close")


class _Publisher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0
        self.staged: _Staged | None = None

    def stage(self, manifest, report, decisions, candidates):
        self.calls += 1
        self.events.append("stage")
        self.staged = _Staged(self.events)
        return self.staged


def _case(status: RuleStatus = RuleStatus.PASS):
    from specstyle.workflow.production_batch import (
        ProductionBatchTarget,
        reserve_production_batch,
    )

    plan = _plan()
    l2_rule = next(
        rule
        for rule in plan.rules
        if rule.metric_id is not None
        and rule.metric_id.value == "batch_style_consistency"
    )
    l3_rule = next(
        rule
        for rule in plan.rules
        if rule.metric_id is not None
        and rule.metric_id.value == "structure_edge_similarity"
    )
    target = ProductionBatchTarget(
        hash_bytes(b"target"),
        hash_bytes(b"compiled"),
        l2_rule.threshold_binding.production_approval_sha256,
        l3_rule.threshold_binding.production_approval_sha256,
        hash_bytes(b"runtime"),
    )
    reservation = reserve_production_batch(
        target.target_cell_sha256,
        (Identifier("member-a"), Identifier("member-b")),
        batch_id=Identifier("batch-1"),
    )
    candidates = tuple(
        _candidate(member.value, index, plan)
        for index, member in enumerate(reservation.member_ids)
    )

    def verify(_manifest, values, rule):
        ids = tuple(item.artifact.ref.artifact_id for item in values)
        score = (
            None
            if status is RuleStatus.UNVERIFIABLE
            else 0.1
            if status is RuleStatus.PASS
            else 0.8
        )
        return RuleResult(rule.definition.rule_id, status, ids, score)

    return plan, target, reservation, candidates, verify


@pytest.mark.parametrize(
    ("batch_status", "artifact_status"),
    (
        (RuleStatus.PASS, ArtifactStatus.APPROVED),
        (RuleStatus.FAIL, ArtifactStatus.REJECTED),
        (RuleStatus.UNVERIFIABLE, ArtifactStatus.REJECTED),
    ),
)
def test_atomic_batch_routes_the_complete_cohort_before_one_publication(
    batch_status: RuleStatus, artifact_status: ArtifactStatus
) -> None:
    from specstyle.workflow.production_batch import run_atomic_production_batch

    plan, target, reservation, candidates, verify = _case(batch_status)
    events: list[str] = []
    publisher = _Publisher(events)

    result = run_atomic_production_batch(
        reservation,
        target,
        plan,
        lambda _reservation: candidates,
        verify,
        publisher,
        checkpoint=lambda phase: events.append(phase.value),
    )

    assert tuple(decision.artifact_status for decision in result.decisions) == (
        artifact_status,
        artifact_status,
    )
    expected_stop = {
        RuleStatus.PASS: RepairStopReason.PASS_ALL_REQUIRED,
        RuleStatus.FAIL: RepairStopReason.NO_IMPROVEMENT,
        RuleStatus.UNVERIFIABLE: RepairStopReason.UNVERIFIABLE,
    }[batch_status]
    assert tuple(decision.repair_stop_reason for decision in result.decisions) == (
        expected_stop,
        expected_stop,
    )
    assert result.manifest.member_ids == reservation.member_ids
    assert result.report.artifacts == tuple(item.artifact.ref for item in candidates)
    assert events == [
        "CANDIDATES_READY",
        "COHORT_FROZEN",
        "BATCH_VERIFIED",
        "ROUTED",
        "stage",
        "EXPORT_STAGED",
        "commit",
        "COMPLETED",
    ]
    assert publisher.calls == 1


@pytest.mark.parametrize("mutation", ("missing", "reordered", "foreign", "duplicate"))
def test_atomic_batch_refuses_nonexact_candidate_cohort(mutation: str) -> None:
    from specstyle.workflow.production_batch import run_atomic_production_batch

    plan, target, reservation, candidates, verify = _case()
    if mutation == "missing":
        candidates = candidates[:-1]
    elif mutation == "reordered":
        candidates = tuple(reversed(candidates))
    elif mutation == "foreign":
        candidates = (
            candidates[0],
            replace(candidates[1], member_id=Identifier("foreign")),
        )
    else:
        candidates = (candidates[0], candidates[0])
    publisher = _Publisher([])

    with pytest.raises(DomainError, match="^invalid production batch cohort$"):
        run_atomic_production_batch(
            reservation,
            target,
            plan,
            lambda _reservation: candidates,
            verify,
            publisher,
        )
    assert publisher.calls == 0


def test_atomic_batch_refuses_batch_result_for_surviving_subset() -> None:
    from specstyle.workflow.production_batch import run_atomic_production_batch

    plan, target, reservation, candidates, _verify = _case()
    publisher = _Publisher([])

    def subset(_manifest, values, rule):
        return RuleResult(
            rule.definition.rule_id,
            RuleStatus.PASS,
            (values[0].artifact.ref.artifact_id,),
            0.0,
        )

    with pytest.raises(DomainError, match="^invalid production batch result$"):
        run_atomic_production_batch(
            reservation,
            target,
            plan,
            lambda _reservation: candidates,
            subset,
            publisher,
        )
    assert publisher.calls == 0


def test_atomic_batch_cancel_after_stage_closes_without_commit() -> None:
    from specstyle.workflow.production_batch import (
        ProductionBatchPhase,
        run_atomic_production_batch,
    )

    plan, target, reservation, candidates, verify = _case()
    events: list[str] = []
    publisher = _Publisher(events)
    cancelled = False

    def checkpoint(phase: ProductionBatchPhase) -> None:
        nonlocal cancelled
        events.append(phase.value)
        if phase is ProductionBatchPhase.EXPORT_STAGED:
            cancelled = True

    with pytest.raises(DomainError, match="^production batch cancelled$"):
        run_atomic_production_batch(
            reservation,
            target,
            plan,
            lambda _reservation: candidates,
            verify,
            publisher,
            checkpoint=checkpoint,
            cancelled=lambda: cancelled,
        )
    assert publisher.staged is not None and publisher.staged.closed
    assert "commit" not in events


def test_frozen_manifest_binds_order_hashes_seeds_and_approvals() -> None:
    from specstyle.workflow.production_batch import freeze_production_cohort

    plan, target, reservation, candidates, _verify = _case()

    first = freeze_production_cohort(reservation, target, plan, candidates)
    second = freeze_production_cohort(reservation, target, plan, candidates)

    assert first == second
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.artifact_sha256s == tuple(
        item.artifact.ref.sha256 for item in candidates
    )
    assert first.seeds == (100, 101)
    assert first.l2_profile_approval_sha256 == target.l2_profile_approval_sha256
    assert first.l3_profile_approval_sha256 == target.l3_profile_approval_sha256


def test_frozen_manifest_rejects_l2_profile_approval_drift() -> None:
    from specstyle.workflow.production_batch import freeze_production_cohort

    plan, target, reservation, candidates, _verify = _case()
    drifted = replace(
        target, l2_profile_approval_sha256=hash_bytes(b"different-approval")
    )

    with pytest.raises(DomainError, match="^invalid production batch plan$"):
        freeze_production_cohort(reservation, drifted, plan, candidates)


@pytest.mark.parametrize("mutation", ("missing_l3", "l3_approval_drift"))
def test_atomic_batch_rejects_invalid_l3_plan_before_build_or_publish(
    mutation: str,
) -> None:
    from specstyle.workflow.production_batch import run_atomic_production_batch

    plan, target, reservation, candidates, verify = _case()
    if mutation == "missing_l3":
        plan = _plan(include_l3=False)
    else:
        target = replace(
            target, l3_profile_approval_sha256=hash_bytes(b"different-l3-approval")
        )
    publisher = _Publisher([])
    build_calls = 0

    def build(_reservation):
        nonlocal build_calls
        build_calls += 1
        return candidates

    with pytest.raises(DomainError, match="^invalid production batch plan$"):
        run_atomic_production_batch(reservation, target, plan, build, verify, publisher)

    assert build_calls == 0
    assert publisher.calls == 0
