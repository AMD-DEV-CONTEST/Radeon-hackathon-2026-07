"""Deterministic approval whitelist property coverage (including batch gates)."""

from __future__ import annotations

import itertools
import random

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    ArtifactStatus,
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)


def artifact(value: str) -> ArtifactRef:
    return ArtifactRef(ArtifactId(value), Sha256("a" * 64))


def test_approved_implies_every_affecting_required_item_and_batch_result_passes() -> (
    None
):
    artifacts = (artifact("one"), artifact("two"))
    statuses = tuple(RuleStatus)
    policies = ("reject", "manual_review")
    cases = list(itertools.product(statuses, statuses, policies, policies))
    random.Random(20260730).shuffle(cases)

    for item_status, batch_status, item_unverifiable, batch_unverifiable in cases:
        item = RuleDefinition(
            RuleId("item"),
            RuleLevel.L1,
            RuleScope.ITEM,
            True,
            StaticApplicability.APPLICABLE,
            GatePolicy("reject", item_unverifiable, "reject"),
        )  # type: ignore[arg-type]
        batch = RuleDefinition(
            RuleId("batch"),
            RuleLevel.L2,
            RuleScope.BATCH,
            True,
            StaticApplicability.APPLICABLE,
            GatePolicy("reject", batch_unverifiable, "reject"),
        )  # type: ignore[arg-type]
        results = (
            RuleResult(RuleId("item"), item_status, (ArtifactId("one"),), None),
            RuleResult(RuleId("item"), item_status, (ArtifactId("two"),), None),
            RuleResult(
                RuleId("batch"),
                batch_status,
                (ArtifactId("one"), ArtifactId("two")),
                None,
            ),
        )
        report = VerificationReport(artifacts, (item, batch), results)
        for target in (ArtifactId("one"), ArtifactId("two")):
            decision = decide_artifact(report, target)
            if decision.artifact_status is ArtifactStatus.APPROVED:
                assert item_status is RuleStatus.PASS
                assert batch_status is RuleStatus.PASS
